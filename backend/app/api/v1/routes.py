from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
import re, secrets, hashlib
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.database import get_db
from app.models.entities import *
from app.security import current_user, require_role
from app.core.config import settings
from app.services.rewards import calculate_reward
from app.api.v1.auth import router as auth_router
from app.api.v1.commerce import router as commerce_router, set_referral_cookie
from app.schemas.commerce import ProductCreate

router = APIRouter()
router.include_router(auth_router)
router.include_router(commerce_router)
def slugify(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") + "-" + secrets.token_hex(3)
def money(n): return Decimal(str(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
def audit(db, actor, action, kind, entity):
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, entity_type=kind, entity_id=str(entity)))

@router.get("/health")
def health(): return {"status":"ok", "service":"crownd-api"}

@router.get("/creators")
def creators(q:str|None=None,niche:str|None=None,platform:str|None=None,limit:int=Query(30,ge=1,le=100),offset:int=0,db:Session=Depends(get_db),user:User=Depends(current_user)):
    stmt=select(CreatorProfile,User).join(User,User.id==CreatorProfile.user_id).where(User.is_active==True)
    if q: stmt=stmt.where((CreatorProfile.username.ilike(f"%{q}%"))|(User.name.ilike(f"%{q}%"))|(CreatorProfile.niche.ilike(f"%{q}%")))
    if niche: stmt=stmt.where(CreatorProfile.niche.ilike(f"%{niche}%"))
    if platform: stmt=stmt.where(CreatorProfile.platform.ilike(platform))
    profiles=db.execute(stmt.offset(offset).limit(limit)).all()
    return [{"user_id":u.id,"name":u.name,"username":p.username,"niche":p.niche,"location":p.location,"platform":p.platform,"followers":p.followers,"engagement":p.engagement,"crown_score":p.crown_score,"trust_score":p.trust_score,"availability":p.availability} for p,u in profiles]
@router.put("/creators/me")
def update_creator(body:dict,db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    p=db.scalar(select(CreatorProfile).where(CreatorProfile.user_id==user.id))
    for k in ("username","niche","location","bio","platform","followers","engagement","availability"):
        if k in body: setattr(p,k,body[k])
    if "name" in body: user.name=body["name"]
    db.commit(); return {"ok":True}

@router.get("/campaigns")
def campaigns(q:str|None=None,status:str="published",limit:int=30,offset:int=0,db:Session=Depends(get_db)):
    stmt=select(Campaign,BrandProfile,User).join(BrandProfile,BrandProfile.user_id==Campaign.brand_id).join(User,User.id==Campaign.brand_id)
    if status!="all": stmt=stmt.where(Campaign.status==status)
    if q: stmt=stmt.where((Campaign.title.ilike(f"%{q}%"))|(Campaign.category.ilike(f"%{q}%"))|(Campaign.description.ilike(f"%{q}%")))
    rows=db.execute(stmt.order_by(Campaign.created_at.desc()).offset(offset).limit(min(limit,100))).all()
    return [{"id":c.id,"title":c.title,"slug":c.slug,"description":c.description,"category":c.category,"platforms":c.platforms,"reward_model":c.reward_model,"reward_rate":float(c.reward_rate),"budget":float(c.budget),"status":c.status,"brand":b.name,"brand_id":c.brand_id,"product_id":c.product_id,"created_at":c.created_at.isoformat()} for c,b,u in rows]
@router.post("/campaigns",status_code=201)
def create_campaign(body:dict,db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    if not body.get("title"): raise HTTPException(422,"Campaign title is required")
    reward_model=body.get("reward_model","percentage")
    if reward_model not in ("percentage","fixed"): raise HTTPException(422,"Unsupported reward model")
    c=Campaign(brand_id=user.id,product_id=body.get("product_id"),title=body["title"],slug=slugify(body["title"]),description=body.get("description",""),category=body.get("category","Lifestyle"),platforms=body.get("platforms","Instagram"),reward_model=reward_model,reward_rate=money(body.get("reward_rate",10)),budget=money(body.get("budget",0)),status="draft")
    db.add(c); db.flush(); audit(db,user,"campaign.created","campaign",c.id); db.commit(); return {"id":c.id,"status":c.status,"slug":c.slug}
@router.get("/campaigns/{campaign_id}")
def campaign_detail(campaign_id:int,db:Session=Depends(get_db)):
    c=db.get(Campaign,campaign_id)
    if not c: raise HTTPException(404,"Campaign not found")
    return {"id":c.id,"title":c.title,"description":c.description,"brand_id":c.brand_id,"product_id":c.product_id,"category":c.category,"reward_model":c.reward_model,"reward_rate":float(c.reward_rate),"budget":float(c.budget),"status":c.status}
@router.patch("/campaigns/{campaign_id}/status")
def change_campaign(campaign_id:int,body:dict,db:Session=Depends(get_db),user:User=Depends(current_user)):
    c=db.get(Campaign,campaign_id)
    if not c: raise HTTPException(404,"Campaign not found")
    if user.role!="admin" and (user.role!="brand" or c.brand_id!=user.id): raise HTTPException(403,"Not your campaign")
    target=body.get("status"); allowed={"draft":{"published"},"published":{"paused","completed","cancelled"},"paused":{"published","cancelled"}}
    if user.role!="admin" and target not in allowed.get(c.status,set()): raise HTTPException(409,"Invalid campaign status transition")
    if target not in {"draft","published","paused","completed","cancelled","rejected"}: raise HTTPException(422,"Unsupported status")
    c.status=target; audit(db,user,"campaign.status_changed","campaign",c.id); db.commit(); return {"id":c.id,"status":c.status}

@router.post("/campaigns/{campaign_id}/applications",status_code=201)
def apply(campaign_id:int,body:dict,db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    c=db.get(Campaign,campaign_id)
    if not c or c.status!="published": raise HTTPException(404,"Campaign is not accepting applications")
    existing=db.scalar(select(Application).where(Application.campaign_id==campaign_id,Application.creator_id==user.id))
    if existing: raise HTTPException(409,"You have already applied to this campaign")
    a=Application(campaign_id=campaign_id,creator_id=user.id,message=body.get("message","")); db.add(a); db.commit(); db.refresh(a); return {"id":a.id,"status":a.status}
@router.get("/applications")
def applications(db:Session=Depends(get_db),user:User=Depends(current_user)):
    stmt=select(Application,Campaign,User).join(Campaign,Campaign.id==Application.campaign_id).join(User,User.id==Application.creator_id)
    if user.role=="creator": stmt=stmt.where(Application.creator_id==user.id)
    elif user.role=="brand": stmt=stmt.where(Campaign.brand_id==user.id)
    elif user.role!="admin": raise HTTPException(403,"Forbidden")
    return [{"id":a.id,"campaign_id":c.id,"campaign":c.title,"creator_id":u.id,"creator":u.name,"message":a.message,"status":a.status,"created_at":a.created_at.isoformat()} for a,c,u in db.execute(stmt.order_by(Application.created_at.desc())).all()]
@router.patch("/applications/{application_id}")
def review_application(application_id:int,body:dict,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=db.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    c=db.get(Campaign,a.campaign_id)
    if user.role!="admin" and (user.role!="brand" or c.brand_id!=user.id): raise HTTPException(403,"Forbidden")
    status=body.get("status")
    if status not in ("shortlisted","accepted","rejected"): raise HTTPException(422,"Invalid application status")
    a.status=status
    if status=="accepted" and not db.scalar(select(Referral).where(Referral.campaign_id==c.id,Referral.creator_id==a.creator_id)):
        code=(re.sub(r"[^A-Z0-9]","",c.title.upper())[:5] or "CROWN")+secrets.token_hex(3).upper()
        db.add(Referral(campaign_id=c.id,creator_id=a.creator_id,code=code))
    audit(db,user,f"application.{status}","application",a.id); db.commit(); return {"id":a.id,"status":status}

@router.post("/products",status_code=201)
def create_product(body:ProductCreate,db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    if body.sale_price is not None and body.sale_price >= body.price:
        raise HTTPException(422,"Sale price must be below regular price")
    p=Product(brand_id=user.id,name=body.name,slug=slugify(body.name),description=body.description,category=body.category,price=money(body.price),sale_price=money(body.sale_price) if body.sale_price is not None else None,stock=body.stock,image_url=body.image_url,image_urls=body.image_urls,specifications=body.specifications)
    db.add(p); db.commit(); db.refresh(p); return {"id":p.id,"slug":p.slug}

@router.get("/referrals/me")
def my_referrals(db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    rows=db.execute(select(Referral,Campaign).join(Campaign,Campaign.id==Referral.campaign_id).where(Referral.creator_id==user.id)).all()
    return [{"id":r.id,"campaign_id":c.id,"campaign":c.title,"code":r.code,"clicks":r.clicks,"active":r.active,"url":f"/r/{r.code}"} for r,c in rows]
@router.get("/r/{code}")
def track_referral(code:str,response:Response,db:Session=Depends(get_db)):
    ref=db.scalar(select(Referral).where(Referral.code==code.upper(),Referral.active==True))
    if not ref: raise HTTPException(404,"Referral code not found")
    c=db.get(Campaign,ref.campaign_id)
    creator=db.get(User,ref.creator_id)
    if c.status!="published" or not creator or not creator.is_active or not creator.email_verified: raise HTTPException(410,"Referral is no longer active")
    ref.clicks+=1
    db.add(Click(referral_id=ref.id)); db.commit()
    set_referral_cookie(response,ref)
    p=db.get(Product,c.product_id) if c.product_id else None
    return {"ok":True,"campaign_id":c.id,"product_id":p.id if p else None,"destination":f"/products/{p.id}" if p else "/shop","attribution_window_days":settings.attribution_days}

@router.post("/orders",status_code=410)
def create_order():
    raise HTTPException(410,"Guest single-product checkout is retired. Use authenticated cart checkout and select a payment method.")
@router.get("/orders")
def list_orders(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role=="admin": rows=db.scalars(select(Order).order_by(Order.created_at.desc())).all()
    elif user.role=="brand": rows=db.scalars(select(Order).join(Product,Product.id==Order.product_id).where(Product.brand_id==user.id)).all()
    elif user.role=="creator": rows=db.scalars(select(Order).join(Referral,Referral.id==Order.referral_id).where(Referral.creator_id==user.id)).all()
    else: rows=db.scalars(select(Order).where(Order.customer_email==user.email)).all()
    return [{"id":o.public_id,"product_id":o.product_id,"quantity":o.quantity,"amount":float(o.amount),"payment_status":o.payment_status,"status":o.status,"created_at":o.created_at.isoformat()} for o in rows]

@router.get("/rewards/me")
def my_rewards(db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    return [{"id":r.id,"order_id":db.get(Order,r.order_id).public_id,"amount":float(r.amount),"status":r.status,"eligible_at":r.eligible_at.isoformat(),"is_demo":r.is_demo,"payable":not r.is_demo and r.status=="eligible"} for r in db.scalars(select(Reward).where(Reward.creator_id==user.id).order_by(Reward.created_at.desc())).all()]
@router.post("/payouts")
def request_payout(db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    available=db.scalar(select(func.coalesce(func.sum(Reward.amount),0)).where(Reward.creator_id==user.id,Reward.status=="eligible",Reward.is_demo.is_(False))) or Decimal(0)
    pending=db.scalar(select(func.coalesce(func.sum(Payout.amount),0)).where(Payout.creator_id==user.id,Payout.status.in_(["requested","approved"]))) or Decimal(0)
    amount=Decimal(str(available))-Decimal(str(pending))
    if amount<Decimal(settings.minimum_payout): raise HTTPException(409,f"Eligible balance must be at least ₹{settings.minimum_payout}")
    payout=Payout(creator_id=user.id,amount=money(amount)); db.add(payout); db.flush(); audit(db,user,"payout.requested","payout",payout.id); db.commit(); return {"id":payout.id,"amount":float(payout.amount),"status":payout.status}

@router.get("/analytics/overview")
def analytics(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role=="admin":
        users=db.scalar(select(func.count(User.id))) or 0; campaigns=db.scalar(select(func.count(Campaign.id))) or 0; orders=db.scalar(select(func.count(Order.id)).where(Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))) or 0; gmv=db.scalar(select(func.coalesce(func.sum(Order.amount),0)).where(Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))) or 0
        return {"users":users,"campaigns":campaigns,"orders":orders,"gmv":float(gmv)}
    if user.role=="brand":
        campaigns=db.scalars(select(Campaign).where(Campaign.brand_id==user.id)).all(); ids=[c.id for c in campaigns]
        products=db.select if False else None
        clicks=db.scalar(select(func.coalesce(func.sum(Referral.clicks),0)).where(Referral.campaign_id.in_(ids))) if ids else 0
        orders=db.scalars(select(Order).join(Referral,Referral.id==Order.referral_id).join(Campaign,Campaign.id==Referral.campaign_id).where(Campaign.brand_id==user.id,Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))).all()
        return {"campaigns":len(campaigns),"clicks":clicks or 0,"orders":len(orders),"revenue":float(sum((o.amount for o in orders),Decimal(0))),"rewards":float(db.scalar(select(func.coalesce(func.sum(Reward.amount),0)).join(Order,Reward.order_id==Order.id).join(Referral,Referral.id==Order.referral_id).join(Campaign,Campaign.id==Referral.campaign_id).where(Campaign.brand_id==user.id,Reward.is_demo.is_(False))) or 0)}
    if user.role=="creator":
        refs=db.scalars(select(Referral).where(Referral.creator_id==user.id)).all(); ids=[r.id for r in refs]
        rewards=db.scalars(select(Reward).where(Reward.creator_id==user.id,Reward.is_demo.is_(False))).all()
        orders=db.scalar(select(func.count(Order.id)).where(Order.referral_id.in_(ids),Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))) if ids else 0
        return {"clicks":sum(r.clicks for r in refs),"orders":orders or 0,"earnings":float(sum((r.amount for r in rewards),Decimal(0))),"pending":float(sum((r.amount for r in rewards if r.status=="pending"),Decimal(0))),"eligible":float(sum((r.amount for r in rewards if r.status=="eligible"),Decimal(0))),"active_campaigns":len(refs)}
    return {"orders":db.scalar(select(func.count(Order.id)).where(Order.customer_email==user.email)) or 0}
@router.get("/ai/matches/{campaign_id}")
def matches(campaign_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("brand","admin"))):
    c=db.get(Campaign,campaign_id)
    if not c: raise HTTPException(404,"Campaign not found")
    if user.role=="brand" and c.brand_id!=user.id: raise HTTPException(403,"Forbidden")
    rows=db.execute(select(CreatorProfile,User).join(User,User.id==CreatorProfile.user_id).where(CreatorProfile.availability==True)).all()
    recs=[]
    for p,u in rows:
        niche=100 if c.category.lower() in p.niche.lower() or p.niche.lower() in c.category.lower() else 35
        engagement=min(100,int(p.engagement*10))
        platform=100 if p.platform.lower() in c.platforms.lower() else 30
        score=round(niche*.30+engagement*.20+platform*.20+min(p.crown_score/10,100)*.15+p.trust_score*.15)
        reasons=[]
        if niche>=70: reasons.append("Niche aligns with campaign category")
        if engagement>=60: reasons.append("Strong creator-reported engagement")
        if platform==100: reasons.append(f"Active on {p.platform}")
        recs.append({"user_id":u.id,"name":u.name,"username":p.username,"niche":p.niche,"platform":p.platform,"followers":p.followers,"engagement":p.engagement,"score":score,"reasons":reasons or ["Available creator; consider reviewing audience fit"]})
    return sorted(recs,key=lambda x:x["score"],reverse=True)[:30]

@router.get("/analytics/timeseries")
def analytics_timeseries(db:Session=Depends(get_db),user:User=Depends(current_user)):
    from calendar import month_abbr
    from collections import defaultdict
    if user.role=="admin": stmt=select(Order).where(Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))
    elif user.role=="brand": stmt=select(Order).join(Product,Product.id==Order.product_id).where(Product.brand_id==user.id,Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))
    elif user.role=="creator": stmt=select(Order).join(Referral,Referral.id==Order.referral_id).where(Referral.creator_id==user.id,Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))
    else: stmt=select(Order).where(Order.customer_email==user.email,Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))
    since=datetime.now(timezone.utc)-timedelta(days=210)
    monthly=defaultdict(lambda: {"revenue":Decimal(0),"orders":0})
    for order in db.scalars(stmt.where(Order.created_at>=since)).all():
        key=order.created_at.strftime("%Y-%m"); monthly[key]["revenue"]+=Decimal(order.amount); monthly[key]["orders"]+=1
    current=datetime.now(timezone.utc).replace(day=1)
    series=[]
    for i in range(6,-1,-1):
        month_index=current.year*12+current.month-1-i
        year,month=divmod(month_index,12); month+=1
        key=f"{year:04d}-{month:02d}"
        series.append({"month":month_abbr[month],"revenue":float(monthly[key]["revenue"]),"orders":monthly[key]["orders"]})
    return series

@router.get("/admin/audit-logs")
def audit_logs(db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    return [{"id":a.id,"actor_id":a.actor_id,"action":a.action,"entity_type":a.entity_type,"entity_id":a.entity_id,"created_at":a.created_at.isoformat()} for a in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()]
@router.get("/admin/users")
def admin_users(db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    return [{"id":u.id,"name":u.name,"email":u.email,"role":u.role,"active":u.is_active,"created_at":u.created_at.isoformat()} for u in db.scalars(select(User).order_by(User.created_at.desc()).limit(300)).all()]
