"""Role-scoped creator reward, financial ledger, and admin management APIs."""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select, func, or_, and_, case, exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.v1.auth import limiter
from app.core.config import settings
from app.database import get_db
from app.models.entities import (Application, AuditLog, BrandProfile, Campaign, Conversion, LedgerEntry,
    Order, OrderItem, Product, Referral, ReferralRiskFlag, Reward, RewardEvent, RewardRule, SimulatedPayout, User)
from app.schemas.commerce import RewardReviewAction, RewardRuleCreate, RewardRuleUpdate
from app.security import require_role
from app.services.referrals import eligible_product_ids
from app.services.rewards_engine import (approve_reward, cash, record_simulated_payout, reject_reward,
    reverse_reward, rule_scope_key, validate_rule_values)

router=APIRouter()


def _dt(value): return value.isoformat() if value else None


def _reward_payload(db:Session,reward:Reward,*,include_history:bool=False,include_risk_details:bool=False):
    order=db.get(Order,reward.order_id)
    campaign=db.get(Campaign,reward.campaign_id) if reward.campaign_id else None
    conversion=db.get(Conversion,reward.conversion_id) if reward.conversion_id else None
    snapshot=reward.calculation_snapshot or {}
    items=snapshot.get("items",[])
    if not items and reward.order_item_id:
        line=db.get(OrderItem,reward.order_item_id)
        if line: items=[{"order_item_id":line.id,"product_id":line.product_id,"quantity":line.quantity,"line_total":str(line.line_total)}]
    products=[]
    for item in items:
        product=db.get(Product,item.get("product_id")) if item.get("product_id") else None
        products.append({"order_item_id":item.get("order_item_id"),"product_id":item.get("product_id"),"product_name":product.name if product else "Historical product","quantity":item.get("quantity"),"line_total":item.get("line_total")})
    payload={"id":reward.id,"order_id":order.public_id if order else str(reward.order_id),"order_pk":reward.order_id,
        "creator_id":reward.creator_id,"brand_id":reward.brand_id,"campaign_id":reward.campaign_id,
        "campaign":campaign.title if campaign else "Historical campaign","conversion_id":reward.conversion_id,
        "product_id":reward.product_id,"products":products,"reward_rule_id":reward.reward_rule_id,
        "reward_type":reward.reward_type,"reward_rate":str(reward.reward_rate) if reward.reward_rate is not None else None,
        "fixed_amount":str(reward.fixed_amount) if reward.fixed_amount is not None else None,
        "amount":str(reward.amount),"eligible_amount":str(reward.eligible_amount),"excluded_amount":str(reward.excluded_amount),
        "currency":reward.currency,"formula":reward.calculation_formula,"rounding_rule":reward.rounding_rule,
        "calculation_snapshot":snapshot,"status":reward.status,"risk_status":reward.risk_status,"is_demo":reward.is_demo,
        "payment_method":order.payment_method if order else "legacy","payment_status":order.payment_status if order else "unknown",
        "order_status":order.status if order else "unknown","eligible_at":_dt(reward.eligible_at),
        "created_at":_dt(reward.created_at),"updated_at":_dt(reward.updated_at),
        "payable":False,"payout_disclosure":"CROWND does not transfer money. Payout records are simulation only."}
    if include_history:
        payload["ledger_entries"]=[_ledger_payload(row) for row in db.scalars(select(LedgerEntry).where(LedgerEntry.reward_id==reward.id).order_by(LedgerEntry.id)).all()]
        payload["events"]=[_event_payload(row) for row in db.scalars(select(RewardEvent).where(RewardEvent.reward_id==reward.id).order_by(RewardEvent.created_at,RewardEvent.id)).all()]
        payload["simulated_payouts"]=[{"id":row.id,"reference":row.reference,"amount":str(row.amount),"currency":row.currency,"created_at":_dt(row.created_at),"disclosure":row.disclosure} for row in db.scalars(select(SimulatedPayout).where(SimulatedPayout.reward_id==reward.id)).all()]
        payload["risk_flags"]=[{"id":row.id,"risk_code":row.risk_code,"status":row.status,"details":row.details if include_risk_details else None,"created_at":_dt(row.created_at)} for row in db.scalars(select(ReferralRiskFlag).where(or_(ReferralRiskFlag.conversion_id==reward.conversion_id,ReferralRiskFlag.referral_id.in_(select(OrderItem.referral_id).where(OrderItem.order_id==reward.order_id,OrderItem.referral_id.is_not(None))))).order_by(ReferralRiskFlag.created_at.desc())).all()]
        payload["approvals"]=[_event_payload(row) for row in db.scalars(select(RewardEvent).where(RewardEvent.reward_id==reward.id,RewardEvent.event_type.in_(["reward_approved","reward_rejected"])).order_by(RewardEvent.created_at)).all()]
        payload["audit_history"]=[{"id":row.id,"action":row.action,"actor_id":row.actor_id,"created_at":_dt(row.created_at)} for row in db.scalars(select(AuditLog).where(AuditLog.entity_type=="reward",AuditLog.entity_id==str(reward.id)).order_by(AuditLog.created_at.desc())).all()]
    return payload


def _ledger_payload(row:LedgerEntry):
    return {"id":row.id,"entry_type":row.entry_type,"amount":str(row.amount),"currency":row.currency,"direction":row.direction,
        "reference":row.reference,"idempotency_key":row.idempotency_key,"reward_id":row.reward_id,"order_id":row.order_id,
        "conversion_id":row.conversion_id,"campaign_id":row.campaign_id,"reversal_of_id":row.reversal_of_id,
        "actor_id":row.actor_id,"description":row.description,"created_at":_dt(row.created_at)}


def _event_payload(row:RewardEvent):
    return {"id":row.id,"event_key":row.event_key,"event_type":row.event_type,"from_status":row.from_status,
        "to_status":row.to_status,"reason":row.reason,"actor_id":row.actor_id,"metadata":row.metadata_json,"created_at":_dt(row.created_at)}


def _filters(stmt,*,status=None,campaign_id=None,product_id=None,is_demo=None,payment_method=None,reward_type=None,start=None,end=None,risk=None):
    if status: stmt=stmt.where(Reward.status==status)
    if campaign_id: stmt=stmt.where(Reward.campaign_id==campaign_id)
    if product_id: stmt=stmt.where(or_(Reward.product_id==product_id,exists(select(OrderItem.id).where(OrderItem.order_id==Reward.order_id,OrderItem.referral_id==Reward.referral_id,OrderItem.product_id==product_id))))
    if is_demo is not None: stmt=stmt.where(Reward.is_demo.is_(is_demo))
    if payment_method: stmt=stmt.join(Order,Order.id==Reward.order_id).where(Order.payment_method==payment_method)
    if reward_type: stmt=stmt.where(Reward.reward_type==reward_type)
    if start: stmt=stmt.where(Reward.created_at>=start)
    if end: stmt=stmt.where(Reward.created_at<end)
    if risk is not None:
        open_risk=exists(select(ReferralRiskFlag.id).where(ReferralRiskFlag.status=="open",or_(ReferralRiskFlag.conversion_id==Reward.conversion_id,ReferralRiskFlag.referral_id==Reward.referral_id)))
        stmt=stmt.where(open_risk if risk else ~open_risk)
    return stmt


def _summary(db:Session,stmt):
    rows=db.execute(stmt.with_only_columns(Reward.status,Reward.is_demo,func.sum(Reward.amount)).order_by(None).group_by(Reward.status,Reward.is_demo)).all()
    data={(status,demo):Decimal(total or 0) for status,demo,total in rows}
    def total(statuses,demo=False): return cash(sum((value for (status,is_demo),value in data.items() if status in statuses and is_demo==demo),Decimal(0)))
    q=stmt.with_only_columns(func.count(Reward.id)).order_by(None).scalar_subquery()
    count=db.scalar(select(q)) or 0
    ledger_stmt=select(func.coalesce(func.sum(case((LedgerEntry.direction=="credit",LedgerEntry.amount),else_=0)),0),func.coalesce(func.sum(case((LedgerEntry.direction=="debit",LedgerEntry.amount),else_=0)),0)).join(Reward,Reward.id==LedgerEntry.reward_id).where(Reward.is_demo.is_(False))
    reward_ids=stmt.with_only_columns(Reward.id).order_by(None).subquery()
    ledger_stmt=ledger_stmt.where(LedgerEntry.reward_id.in_(select(reward_ids.c.id)))
    credit,debit=db.execute(ledger_stmt).one()
    sim_sum=total({"simulated"},True)
    return {"reward_count":count,"total_rewards_generated":str(total({"pending_collection","pending","under_review","approved","rejected","reversed"},False)),
        "pending_collection":str(total({"pending_collection"},False)),"pending":str(total({"pending"},False)),
        "eligible":str(total({"pending","eligible"},False)),"under_review":str(total({"under_review"},False)),
        "approved":str(total({"approved"},False)),"reversed":str(total({"reversed"},False)),"rejected":str(total({"rejected"},False)),
        "simulated_rewards":str(sim_sum),"net_actual_reward_liability":str(cash(Decimal(credit or 0)-Decimal(debit or 0))),
        "simulated_payouts_recorded":db.scalar(select(func.count(SimulatedPayout.id)).join(Reward,Reward.id==SimulatedPayout.reward_id).where(Reward.id.in_(select(reward_ids.c.id)))) or 0,
        "simulated_payout_amount":str(cash(db.scalar(select(func.coalesce(func.sum(SimulatedPayout.amount),0)).join(Reward,Reward.id==SimulatedPayout.reward_id).where(Reward.id.in_(select(reward_ids.c.id)))) or 0)),
        "actual_money_transferred":False,"disclosure":"Simulated payout records are not money transfers."}


def _rule_payload(rule:RewardRule):
    return {"id":rule.id,"campaign_id":rule.campaign_id,"product_id":rule.product_id,"scope_key":rule.scope_key,
        "reward_type":rule.reward_type,"rate":str(rule.rate) if rule.rate is not None else None,
        "fixed_amount":str(rule.fixed_amount) if rule.fixed_amount is not None else None,"currency":rule.currency,
        "minimum_eligible_amount":str(rule.minimum_eligible_amount),"max_reward":str(rule.max_reward) if rule.max_reward is not None else None,
        "max_creator_total":str(rule.max_creator_total) if rule.max_creator_total is not None else None,
        "max_campaign_total":str(rule.max_campaign_total) if rule.max_campaign_total is not None else None,
        "active":rule.active,"valid_from":_dt(rule.valid_from),"valid_until":_dt(rule.valid_until),
        "created_by":rule.created_by,"updated_by":rule.updated_by,"created_at":_dt(rule.created_at),"updated_at":_dt(rule.updated_at)}


def _date_bounds(start:datetime|None,end:datetime|None):
    if start and end and start>=end: raise HTTPException(422,"Start date must be earlier than end date")
    return start,end


@router.get("/creator/earnings/summary")
def creator_earnings_summary(db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    return _summary(db,select(Reward).where(Reward.creator_id==user.id))


@router.get("/creator/rewards")
def creator_rewards(status:str|None=None,campaign_id:int|None=Query(None,gt=0),product_id:int|None=Query(None,gt=0),is_demo:bool|None=None,
    payment_method:str|None=Query(None,pattern="^(demo|cod|online|legacy)$"),reward_type:str|None=Query(None,pattern="^(percentage|fixed)$"),
    start:datetime|None=None,end:datetime|None=None,risk:bool|None=None,q:str|None=Query(None,max_length=100),page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),
    db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    start,end=_date_bounds(start,end);stmt=_filters(select(Reward).where(Reward.creator_id==user.id),status=status,campaign_id=campaign_id,product_id=product_id,is_demo=is_demo,payment_method=payment_method,reward_type=reward_type,start=start,end=end,risk=risk)
    if q: stmt=stmt.join(Order,Order.id==Reward.order_id).where(Order.public_id.ilike(f"%{q.strip()}%"))
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.scalars(stmt.order_by(Reward.created_at.desc(),Reward.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[_reward_payload(db,row) for row in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size,"summary":_summary(db,stmt)}


@router.get("/creator/rewards/{reward_id}")
def creator_reward_detail(reward_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    reward=db.scalar(select(Reward).where(Reward.id==reward_id,Reward.creator_id==user.id))
    if not reward: raise HTTPException(404,"Reward not found")
    return _reward_payload(db,reward,include_history=True)


@router.get("/creator/ledger")
def creator_ledger(start:datetime|None=None,end:datetime|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    start,end=_date_bounds(start,end);stmt=select(LedgerEntry).where(LedgerEntry.user_id==user.id)
    if start:stmt=stmt.where(LedgerEntry.created_at>=start)
    if end:stmt=stmt.where(LedgerEntry.created_at<end)
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.scalars(stmt.order_by(LedgerEntry.created_at.desc(),LedgerEntry.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[_ledger_payload(row) for row in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size}


@router.get("/brand/reward-analytics")
def brand_reward_analytics(campaign_id:int|None=Query(None,gt=0),creator_id:int|None=Query(None,gt=0),product_id:int|None=Query(None,gt=0),start:datetime|None=None,end:datetime|None=None,
    db:Session=Depends(get_db),user:User=Depends(require_role("brand","admin"))):
    start,end=_date_bounds(start,end);stmt=select(Reward).where(Reward.brand_id==user.id if user.role=="brand" else True)
    if campaign_id:stmt=stmt.where(Reward.campaign_id==campaign_id)
    if creator_id:stmt=stmt.where(Reward.creator_id==creator_id)
    stmt=_filters(stmt,product_id=product_id,start=start,end=end)
    summary=_summary(db,stmt)
    grouped=db.execute(select(Reward.campaign_id,Reward.creator_id,Reward.status,Reward.is_demo,func.count(Reward.id),func.sum(Reward.eligible_amount),func.sum(Reward.amount))
        .where(Reward.id.in_(select(stmt.with_only_columns(Reward.id).order_by(None).subquery().c.id))).group_by(Reward.campaign_id,Reward.creator_id,Reward.status,Reward.is_demo)).all()
    campaigns={};creators={}
    for cid,creator,status,demo,count,eligible,amount in grouped:
        campaign=campaigns.setdefault(cid,{"campaign_id":cid,"campaign":"Campaign","reward_records":0,"eligible_sales":Decimal(0),"reward_liability":Decimal(0),"pending":Decimal(0),"approved":Decimal(0),"reversed":Decimal(0),"simulated_rewards":Decimal(0)})
        if cid:
            campaign["campaign"]=db.get(Campaign,cid).title if db.get(Campaign,cid) else "Historical campaign"
        campaign["reward_records"]+=count
        campaign["eligible_sales"]+=Decimal(eligible or 0)
        if demo:campaign["simulated_rewards"]+=Decimal(amount or 0)
        elif status not in {"reversed","rejected"}:campaign["reward_liability"]+=Decimal(amount or 0)
        if not demo and status in {"pending","under_review","pending_collection"}:campaign["pending"]+=Decimal(amount or 0)
        if not demo and status=="approved":campaign["approved"]+=Decimal(amount or 0)
        if not demo and status=="reversed":campaign["reversed"]+=Decimal(amount or 0)
        key=(cid,creator);entry=creators.setdefault(key,{"campaign_id":cid,"creator_id":creator,"creator":"Creator","reward_records":0,"eligible_sales":Decimal(0),"reward_amount":Decimal(0),"pending":Decimal(0),"approved":Decimal(0),"reversed":Decimal(0),"simulated_rewards":Decimal(0)})
        person=db.get(User,creator) if creator else None;entry["creator"]=person.name if person else "Historical creator"
        entry["reward_records"]+=count;entry["eligible_sales"]+=Decimal(eligible or 0)
        if demo:entry["simulated_rewards"]+=Decimal(amount or 0)
        elif status not in {"reversed","rejected"}:entry["reward_amount"]+=Decimal(amount or 0)
        if not demo and status in {"pending","under_review","pending_collection"}:entry["pending"]+=Decimal(amount or 0)
        if not demo and status=="approved":entry["approved"]+=Decimal(amount or 0)
        if not demo and status=="reversed":entry["reversed"]+=Decimal(amount or 0)
    def clean(row): return {k:(str(cash(v)) if isinstance(v,Decimal) else v) for k,v in row.items()}
    return {"summary":summary,"campaigns":[clean(row) for row in campaigns.values()],"creators":[clean(row) for row in creators.values()],"customer_data_excluded":True}


@router.get("/admin/rewards/summary")
def admin_reward_summary(db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    summary=_summary(db,select(Reward))
    open_risk=db.scalar(select(func.count(ReferralRiskFlag.id)).where(ReferralRiskFlag.status=="open")) or 0
    summary["risk_flagged_rewards"]=db.scalar(select(func.count(Reward.id)).where(exists(select(ReferralRiskFlag.id).where(ReferralRiskFlag.status=="open",or_(ReferralRiskFlag.conversion_id==Reward.conversion_id,ReferralRiskFlag.referral_id==Reward.referral_id)))) ) or 0
    summary["open_referral_risk_flags"]=open_risk
    summary["actual_money_transferred"]=False
    return summary


@router.get("/admin/rewards")
def admin_rewards(q:str|None=Query(None,max_length=120),status:str|None=None,creator_id:int|None=Query(None,gt=0),brand_id:int|None=Query(None,gt=0),campaign_id:int|None=Query(None,gt=0),order_id:str|None=None,conversion_id:int|None=Query(None,gt=0),product_id:int|None=Query(None,gt=0),is_demo:bool|None=None,payment_method:str|None=Query(None,pattern="^(demo|cod|online|legacy)$"),reward_type:str|None=Query(None,pattern="^(percentage|fixed)$"),risk:bool|None=None,start:datetime|None=None,end:datetime|None=None,page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    start,end=_date_bounds(start,end);stmt=_filters(select(Reward),status=status,campaign_id=campaign_id,product_id=product_id,is_demo=is_demo,payment_method=payment_method,reward_type=reward_type,start=start,end=end,risk=risk)
    if creator_id:stmt=stmt.where(Reward.creator_id==creator_id)
    if brand_id:stmt=stmt.where(Reward.brand_id==brand_id)
    if conversion_id:stmt=stmt.where(Reward.conversion_id==conversion_id)
    if order_id:stmt=stmt.join(Order,Order.id==Reward.order_id).where(Order.public_id==order_id)
    if q:
        term=f"%{q.strip()}%"
        stmt=stmt.join(Order,Order.id==Reward.order_id).outerjoin(User,User.id==Reward.creator_id).where(or_(Order.public_id.ilike(term),User.name.ilike(term),User.email.ilike(term),Reward.campaign_id.cast(__import__('sqlalchemy').String).ilike(term)))
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.scalars(stmt.order_by(Reward.created_at.desc(),Reward.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[_reward_payload(db,row) for row in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size,"summary":_summary(db,stmt)}


@router.get("/admin/rewards/{reward_id}")
def admin_reward_detail(reward_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    reward=db.get(Reward,reward_id)
    if not reward:raise HTTPException(404,"Reward not found")
    return _reward_payload(db,reward,include_history=True,include_risk_details=True)


@router.get("/admin/ledger")
def admin_ledger(creator_id:int|None=Query(None,gt=0),reward_id:int|None=Query(None,gt=0),order_id:int|None=Query(None,gt=0),entry_type:str|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    stmt=select(LedgerEntry)
    if creator_id:stmt=stmt.where(LedgerEntry.user_id==creator_id)
    if reward_id:stmt=stmt.where(LedgerEntry.reward_id==reward_id)
    if order_id:stmt=stmt.where(LedgerEntry.order_id==order_id)
    if entry_type:stmt=stmt.where(LedgerEntry.entry_type==entry_type)
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.scalars(stmt.order_by(LedgerEntry.created_at.desc(),LedgerEntry.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[_ledger_payload(row) for row in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size}


@router.get("/admin/rewards/{reward_id}/history")
def admin_reward_history(reward_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    reward=db.get(Reward,reward_id)
    if not reward:raise HTTPException(404,"Reward not found")
    return _reward_payload(db,reward,include_history=True,include_risk_details=True)


@router.post("/admin/reward-rules",status_code=201)
@limiter.limit("30/minute")
def create_reward_rule(body:RewardRuleCreate,request:Request,response:Response,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    campaign=db.get(Campaign,body.campaign_id)
    if not campaign:raise HTTPException(404,"Campaign not found")
    if body.product_id is not None and body.product_id not in eligible_product_ids(db,campaign):raise HTTPException(422,"Product is not eligible for this campaign")
    if body.valid_from and body.valid_until and body.valid_from>=body.valid_until:raise HTTPException(422,"Rule end must follow its start")
    try:validate_rule_values(reward_type=body.reward_type,rate=body.rate,fixed_amount=body.fixed_amount,currency=body.currency,minimum_eligible_amount=body.minimum_eligible_amount,max_reward=body.max_reward,max_creator_total=body.max_creator_total,max_campaign_total=body.max_campaign_total)
    except ValueError as exc:raise HTTPException(422,str(exc))
    scope=rule_scope_key(body.campaign_id,body.product_id)
    existing=db.scalar(select(RewardRule.id).where(RewardRule.scope_key==scope,RewardRule.active.is_(True)))
    if existing:raise HTTPException(409,"An active rule already exists for this campaign/product scope; deactivate it before replacing it")
    rule=RewardRule(campaign_id=body.campaign_id,product_id=body.product_id,scope_key=scope,reward_type=body.reward_type,rate=body.rate,fixed_amount=body.fixed_amount,currency=body.currency,minimum_eligible_amount=body.minimum_eligible_amount,max_reward=body.max_reward,max_creator_total=body.max_creator_total,max_campaign_total=body.max_campaign_total,active=body.active,valid_from=body.valid_from,valid_until=body.valid_until,created_by=user.id,updated_by=user.id)
    db.add(rule);db.flush();db.add(AuditLog(actor_id=user.id,action="reward_rule.created",entity_type="reward_rule",entity_id=str(rule.id)))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"A rule already exists for this campaign/product scope")
    db.refresh(rule);return _rule_payload(rule)


@router.get("/admin/reward-rules")
def list_reward_rules(campaign_id:int|None=Query(None,gt=0),product_id:int|None=Query(None,gt=0),active:bool|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    stmt=select(RewardRule)
    if campaign_id:stmt=stmt.where(RewardRule.campaign_id==campaign_id)
    if product_id is not None:stmt=stmt.where(RewardRule.product_id==product_id)
    if active is not None:stmt=stmt.where(RewardRule.active.is_(active))
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.scalars(stmt.order_by(RewardRule.campaign_id,RewardRule.product_id,RewardRule.id).offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[_rule_payload(row) for row in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size}


@router.put("/admin/reward-rules/{rule_id}")
@limiter.limit("30/minute")
def update_reward_rule(rule_id:int,body:RewardRuleUpdate,request:Request,response:Response,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    rule=db.scalar(select(RewardRule).where(RewardRule.id==rule_id).with_for_update())
    if not rule:raise HTTPException(404,"Reward rule not found")
    values=body.model_dump(exclude_unset=True)
    merged={name:values.get(name,getattr(rule,name)) for name in ("reward_type","rate","fixed_amount","currency","minimum_eligible_amount","max_reward","max_creator_total","max_campaign_total")}
    if merged["reward_type"]=="percentage" and "reward_type" in values and "rate" not in values:merged["fixed_amount"]=None
    if merged["reward_type"]=="fixed" and "reward_type" in values and "fixed_amount" not in values:merged["rate"]=None
    if "valid_from" in values and "valid_until" not in values:values["valid_until"]=rule.valid_until
    if "valid_until" in values and "valid_from" not in values:values["valid_from"]=rule.valid_from
    valid_from=values.get("valid_from",rule.valid_from);valid_until=values.get("valid_until",rule.valid_until)
    if valid_from and valid_until and valid_from>=valid_until:raise HTTPException(422,"Rule end must follow its start")
    try:validate_rule_values(**merged)
    except ValueError as exc:raise HTTPException(422,str(exc))
    if values.get("active") is True:
        conflict=db.scalar(select(RewardRule.id).where(RewardRule.scope_key==rule.scope_key,RewardRule.active.is_(True),RewardRule.id!=rule.id))
        if conflict:raise HTTPException(409,"Another active rule already exists for this campaign/product scope")
    for name,value in values.items():setattr(rule,name,value)
    if "reward_type" in values:rule.rate=merged["rate"];rule.fixed_amount=merged["fixed_amount"]
    rule.updated_by=user.id;rule.updated_at=datetime.now(timezone.utc)
    db.add(AuditLog(actor_id=user.id,action="reward_rule.updated",entity_type="reward_rule",entity_id=str(rule.id)));db.commit();return _rule_payload(rule)


@router.patch("/admin/reward-rules/{rule_id}/active")
@limiter.limit("30/minute")
def set_reward_rule_active(rule_id:int,active:bool,request:Request,response:Response,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    rule=db.scalar(select(RewardRule).where(RewardRule.id==rule_id).with_for_update())
    if not rule:raise HTTPException(404,"Reward rule not found")
    if active and db.scalar(select(RewardRule.id).where(RewardRule.scope_key==rule.scope_key,RewardRule.active.is_(True),RewardRule.id!=rule.id)):
        raise HTTPException(409,"Another active rule already exists for this campaign/product scope")
    rule.active=active;rule.updated_by=user.id;rule.updated_at=datetime.now(timezone.utc)
    db.add(AuditLog(actor_id=user.id,action="reward_rule.activated" if active else "reward_rule.deactivated",entity_type="reward_rule",entity_id=str(rule.id)));db.commit();return _rule_payload(rule)


def _mutate_reward(db:Session,reward_id:int,user:User,action:str,reason:str|None):
    reward=db.scalar(select(Reward).where(Reward.id==reward_id).with_for_update())
    if not reward:raise HTTPException(404,"Reward not found")
    try:
        if action=="approve":approve_reward(db,reward,user.id)
        elif action=="reject":reject_reward(db,reward,user.id,reason or "Rejected by administrator")
        elif action=="reverse":reverse_reward(db,reward,user.id,reason or "Administrative correction")
        elif action=="simulate":
            payout=record_simulated_payout(db,reward,user.id)
            db.add(AuditLog(actor_id=user.id,action="reward.simulated_payout_recorded",entity_type="reward",entity_id=str(reward.id)))
            db.commit();return {"payout_id":payout.id,"reference":payout.reference,"amount":str(payout.amount),"currency":payout.currency,"disclosure":payout.disclosure,"actual_money_transferred":False}
    except ValueError as exc:
        db.rollback();raise HTTPException(409,str(exc))
    reward.updated_at=datetime.now(timezone.utc)
    db.add(AuditLog(actor_id=user.id,action=f"reward.{action}",entity_type="reward",entity_id=str(reward.id)))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"This reward action has already been processed")
    db.refresh(reward);return _reward_payload(db,reward,include_history=True,include_risk_details=True)


@router.post("/admin/rewards/{reward_id}/approve")
@limiter.limit("60/minute")
def approve_reward_route(reward_id:int,body:RewardReviewAction,request:Request,response:Response,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    return _mutate_reward(db,reward_id,user,"approve",body.reason)


@router.post("/admin/rewards/{reward_id}/reject")
@limiter.limit("60/minute")
def reject_reward_route(reward_id:int,body:RewardReviewAction,request:Request,response:Response,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    if not body.reason:raise HTTPException(422,"A rejection reason is required")
    return _mutate_reward(db,reward_id,user,"reject",body.reason)


@router.post("/admin/rewards/{reward_id}/reverse")
@limiter.limit("30/minute")
def reverse_reward_route(reward_id:int,body:RewardReviewAction,request:Request,response:Response,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    if not body.reason:raise HTTPException(422,"A reversal reason is required")
    return _mutate_reward(db,reward_id,user,"reverse",body.reason)


@router.post("/admin/rewards/{reward_id}/simulated-payout")
@limiter.limit("30/minute")
def simulated_payout_route(reward_id:int,body:RewardReviewAction,request:Request,response:Response,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    return _mutate_reward(db,reward_id,user,"simulate",body.reason)
