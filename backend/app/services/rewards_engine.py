"""Server-authoritative reward calculation, lifecycle, and append-only ledger services."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.entities import (Application, AuditLog, Campaign, Conversion, LedgerEntry, Order, OrderItem,
    Product, Referral, ReferralRiskFlag, Reward, RewardEvent, RewardRule, SimulatedPayout, User)
from app.services.conversions import flag_risk
from app.services.referrals import referral_eligibility

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HOLD_DAYS = 30


def cash(value: Decimal | str | int) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def utc(value: datetime | None) -> datetime | None:
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def self_referral(db: Session, referral: Referral, customer: User) -> bool:
    creator=db.get(User,referral.creator_id)
    return bool(creator and (creator.id==customer.id or creator.email.strip().casefold()==customer.email.strip().casefold()))


def rule_scope_key(campaign_id: int, product_id: int | None) -> str:
    return f"campaign:{campaign_id}:product:{product_id if product_id is not None else 'default'}"


def validate_rule_values(*, reward_type: str, rate: Decimal | None, fixed_amount: Decimal | None,
                         currency: str, minimum_eligible_amount: Decimal, max_reward: Decimal | None,
                         max_creator_total: Decimal | None, max_campaign_total: Decimal | None) -> None:
    if currency != "INR": raise ValueError("Only INR reward rules are currently supported")
    if minimum_eligible_amount < 0: raise ValueError("Minimum eligible amount cannot be negative")
    if reward_type == "percentage":
        if rate is None or rate <= 0 or rate > 100: raise ValueError("Percentage rate must be greater than 0 and at most 100")
        if fixed_amount is not None: raise ValueError("Percentage rules cannot include a fixed amount")
    elif reward_type == "fixed":
        if fixed_amount is None or fixed_amount <= 0: raise ValueError("Fixed reward must be greater than zero")
        if rate is not None: raise ValueError("Fixed rules cannot include a percentage rate")
    else: raise ValueError("Unsupported reward type")
    for label,value in (("Maximum reward",max_reward),("Creator cap",max_creator_total),("Campaign cap",max_campaign_total)):
        if value is not None and value <= 0: raise ValueError(f"{label} must be greater than zero")


def select_reward_rule(db: Session, campaign: Campaign, product: Product, at: datetime):
    at=utc(at) or datetime.now(timezone.utc)
    base=(RewardRule.campaign_id==campaign.id,RewardRule.active.is_(True),
          ((RewardRule.valid_from.is_(None))|(RewardRule.valid_from<=at)),
          ((RewardRule.valid_until.is_(None))|(RewardRule.valid_until>=at)))
    product_rule=db.scalar(select(RewardRule).where(*base,RewardRule.product_id==product.id).order_by(RewardRule.id.desc()).with_for_update())
    if product_rule: return product_rule,"product_rule"
    campaign_rule=db.scalar(select(RewardRule).where(*base,RewardRule.product_id.is_(None)).order_by(RewardRule.id.desc()).with_for_update())
    if campaign_rule: return campaign_rule,"campaign_rule"
    return None,"campaign_default"


def _rule_parts(campaign: Campaign, rule: RewardRule | None):
    if rule:
        return rule.reward_type, (Decimal(rule.rate) if rule.rate is not None else None), (Decimal(rule.fixed_amount) if rule.fixed_amount is not None else None), rule.currency
    reward_type=campaign.reward_model
    value=Decimal(campaign.reward_rate)
    return reward_type, (value if reward_type=="percentage" else None), (value if reward_type=="fixed" else None), "INR"


def _calculation(amount: Decimal, reward_type: str, rate: Decimal | None, fixed: Decimal | None) -> tuple[Decimal,str]:
    eligible=cash(amount)
    if reward_type=="percentage":
        if rate is None: raise ValueError("Percentage rule is missing a rate")
        formula=f"{eligible} * {rate} / 100"
        return cash(eligible*rate/Decimal("100")),formula
    if reward_type=="fixed":
        if fixed is None: raise ValueError("Fixed rule is missing a fixed amount")
        formula=f"fixed {cash(fixed)} per eligible order-item group"
        return cash(fixed),formula
    raise ValueError("Unsupported reward type")


def _is_open_risk(db: Session, referral_id: int, conversion_id: int) -> bool:
    return bool(db.scalar(select(ReferralRiskFlag.id).where(ReferralRiskFlag.status=="open",
        ((ReferralRiskFlag.referral_id==referral_id)|(ReferralRiskFlag.conversion_id==conversion_id))).limit(1)))


def _reward_has_open_risk(db: Session, reward: Reward, conversion_id: int) -> bool:
    item_ids=(reward.calculation_snapshot or {}).get("item_ids",[])
    referral_ids=list(db.scalars(select(OrderItem.referral_id).where(OrderItem.id.in_(item_ids),OrderItem.referral_id.is_not(None))).all()) if item_ids else []
    condition=ReferralRiskFlag.conversion_id==conversion_id
    if referral_ids: condition=condition|(ReferralRiskFlag.referral_id.in_(referral_ids))
    return bool(db.scalar(select(ReferralRiskFlag.id).where(ReferralRiskFlag.status=="open",condition).limit(1)))


def _event(db: Session, reward: Reward, key: str, event_type: str, old: str | None, new: str,
           actor_id: int | None=None, reason: str | None=None, metadata: dict | None=None):
    if db.scalar(select(RewardEvent.id).where(RewardEvent.reward_id==reward.id,RewardEvent.event_key==key)): return
    db.add(RewardEvent(reward_id=reward.id,event_key=key,event_type=event_type,from_status=old,to_status=new,
        actor_id=actor_id,reason=reason,metadata_json=metadata or {}))


def _ledger(db: Session, *, key: str, user_id: int, reward_id: int, order: Order, conversion: Conversion,
            campaign_id: int | None, entry_type: str, amount: Decimal, direction: str, actor_id: int | None,
            description: str, reversal_of_id: int | None=None):
    if db.scalar(select(LedgerEntry.id).where(LedgerEntry.idempotency_key==key)): return None
    row=LedgerEntry(reference=order.public_id,user_id=user_id,entry_type=entry_type,amount=cash(amount),currency=order.currency or "INR",
        direction=direction,idempotency_key=key,reward_id=reward_id,order_id=order.id,conversion_id=conversion.id,
        campaign_id=campaign_id,reversal_of_id=reversal_of_id,actor_id=actor_id,description=description[:240])
    db.add(row);db.flush();return row


def _record_reward(db: Session, *, order: Order, conversion: Conversion, referral: Referral, campaign: Campaign,
                   product: Product, lines: list[OrderItem], customer: User, demo: bool, stage: str,
                   actor_id: int | None=None) -> Reward | None:
    if not lines or self_referral(db,referral,customer):
        if lines and self_referral(db,referral,customer):
            flag_risk(db,"SELF_REFERRAL",referral_id=referral.id,conversion_id=conversion.id,customer_id=customer.id,
                      visitor_hash=conversion.visitor_hash,details="Buyer matches the referred creator account/email.")
        return None
    eligible_amount=cash(sum((cash(line.line_total) for line in lines),Decimal("0")))
    reward_type_placeholder=None
    rule,rule_source=select_reward_rule(db,campaign,product,order.created_at or datetime.now(timezone.utc))
    ids=[line.id for line in lines]
    token=f"{order.id}:{referral.creator_id}:{campaign.id}:{rule.id if rule else 'campaign-default'}:{','.join(map(str,ids))}"
    source="reward:"+sha256(token.encode()).hexdigest()
    existing=db.scalar(select(Reward).where(Reward.source_key==source))
    if existing:return existing
    reward_type,rate,fixed,currency=_rule_parts(campaign,rule)
    try:
        validate_rule_values(reward_type=reward_type,rate=rate,fixed_amount=fixed,currency=currency,
            minimum_eligible_amount=Decimal(rule.minimum_eligible_amount) if rule else ZERO,
            max_reward=Decimal(rule.max_reward) if rule and rule.max_reward is not None else None,
            max_creator_total=Decimal(rule.max_creator_total) if rule and rule.max_creator_total is not None else None,
            max_campaign_total=Decimal(rule.max_campaign_total) if rule and rule.max_campaign_total is not None else None)
    except ValueError:
        return None
    minimum=Decimal(rule.minimum_eligible_amount) if rule else ZERO
    if eligible_amount < minimum: return None
    amount,formula=_calculation(eligible_amount,reward_type,rate,fixed)
    if rule and rule.max_reward is not None: amount=min(amount,cash(rule.max_reward))
    creator_used_before=ZERO
    rule_campaign_used_before=ZERO
    campaign_budget_used_before=ZERO
    campaign_budget_limit=cash(campaign.budget) if Decimal(campaign.budget or 0)>0 else None
    if not demo:
        # Serialize cap/budget reads for this campaign on PostgreSQL transactions;
        # SQLite test locks are advisory only and do not prove production concurrency.
        db.scalar(select(Campaign.id).where(Campaign.id==campaign.id).with_for_update())
        if rule and rule.max_creator_total is not None:
            creator_used_before=cash(Decimal(db.scalar(select(func.coalesce(func.sum(Reward.amount),0)).where(Reward.reward_rule_id==rule.id,Reward.creator_id==referral.creator_id,Reward.is_demo.is_(False),Reward.status.notin_(["reversed","rejected"]))) or 0))
            amount=min(amount,max(ZERO,cash(rule.max_creator_total)-creator_used_before))
        if rule and rule.max_campaign_total is not None:
            rule_campaign_used_before=cash(Decimal(db.scalar(select(func.coalesce(func.sum(Reward.amount),0)).where(Reward.reward_rule_id==rule.id,Reward.campaign_id==campaign.id,Reward.is_demo.is_(False),Reward.status.notin_(["reversed","rejected"]))) or 0))
            amount=min(amount,max(ZERO,cash(rule.max_campaign_total)-rule_campaign_used_before))
        if campaign_budget_limit is not None:
            campaign_budget_used_before=cash(Decimal(db.scalar(select(func.coalesce(func.sum(Reward.amount),0)).where(Reward.campaign_id==campaign.id,Reward.is_demo.is_(False),Reward.status.notin_(["reversed","rejected"]))) or 0))
            amount=min(amount,max(ZERO,campaign_budget_limit-campaign_budget_used_before))
    amount=cash(amount)
    if amount<=0:return None
    risk=_is_open_risk(db,referral.id,conversion.id)
    if demo: status="simulated"
    elif stage=="collection": status="under_review" if risk else "pending"
    else: status="pending_collection"
    snapshot={"legacy":False,"rule_source":rule_source,"rule_id":rule.id if rule else None,
        "reward_type":reward_type,"rate":str(rate) if rate is not None else None,"fixed_amount":str(fixed) if fixed is not None else None,
        "currency":currency,"original_order_amount":str(cash(order.amount)),"eligible_amount":str(eligible_amount),
        "excluded_amount":str(cash(Decimal(order.amount)-eligible_amount)),"item_ids":ids,
        "items":[{"order_item_id":line.id,"product_id":line.product_id,"quantity":line.quantity,"line_total":str(cash(line.line_total))} for line in lines],
        "maximum_per_reward":str(rule.max_reward) if rule and rule.max_reward is not None else None,
        "creator_cap":str(rule.max_creator_total) if rule and rule.max_creator_total is not None else None,
        "creator_total_used_before":str(creator_used_before),
        "campaign_cap":str(rule.max_campaign_total) if rule and rule.max_campaign_total is not None else None,
        "rule_campaign_total_used_before":str(rule_campaign_used_before),
        "campaign_budget":str(campaign_budget_limit) if campaign_budget_limit is not None else None,
        "campaign_budget_used_before":str(campaign_budget_used_before),
        "formula":formula,"rounding":"ROUND_HALF_UP","calculated_amount":str(amount),"simulation":demo}
    reward=Reward(order_id=order.id,creator_id=referral.creator_id,brand_id=campaign.brand_id,campaign_id=campaign.id,
        conversion_id=conversion.id,referral_id=referral.id,order_item_id=ids[0] if len(ids)==1 else None,product_id=product.id if len({x.product_id for x in lines})==1 else None,
        reward_rule_id=rule.id if rule else None,source_key=source,amount=amount,eligible_amount=eligible_amount,
        excluded_amount=cash(Decimal(order.amount)-eligible_amount),currency=currency,reward_type=reward_type,reward_rate=rate,
        fixed_amount=fixed,calculation_formula=formula,rounding_rule="ROUND_HALF_UP",calculation_snapshot=snapshot,
        status=status,risk_status="under_review" if risk else "clear",eligible_at=(order.created_at or datetime.now(timezone.utc))+timedelta(days=HOLD_DAYS),is_demo=demo)
    db.add(reward);db.flush()
    _event(db,reward,f"created:{source}","reward_created",None,status,actor_id,
        "Simulated reward; no payable liability created." if demo else ("Awaiting COD collection." if stage=="checkout" else "Reward calculated from eligible attributed items."),snapshot)
    if demo:
        _ledger(db,key=f"demo-reward:{source}",user_id=referral.creator_id,reward_id=reward.id,order=order,conversion=conversion,
            campaign_id=campaign.id,entry_type="SIMULATED_REWARD_RECORDED",amount=amount,direction="memo",actor_id=None,
            description="Simulation only; not payable and not a money transfer.")
    elif stage=="collection":
        _ledger(db,key=f"reward-created:{source}",user_id=referral.creator_id,reward_id=reward.id,order=order,conversion=conversion,
            campaign_id=campaign.id,entry_type="REWARD_PENDING",amount=amount,direction="credit",actor_id=actor_id,
            description="Creator reward liability recorded after COD collection.")
    return reward


def generate_order_rewards(db: Session, order: Order, *, stage: str, actor_id: int | None=None) -> list[Reward]:
    """Create one deterministic reward per order/creator/campaign/rule/item group.

    `checkout` creates no COD reward or liability. `collection` is called only
    after authorized collection confirmation; `demo` creates simulation-only rows.
    """
    conversion=db.scalar(select(Conversion).where(Conversion.order_id==order.id))
    if stage=="checkout":
        # COD estimates are intentionally not persisted as rewards or liabilities;
        # no reward exists until an administrator confirms post-delivery collection.
        return []
    if not conversion or conversion.status!="confirmed": return []
    if order.status=="cancelled" or (stage=="collection" and (order.payment_method!="cod" or order.payment_status!="paid")):
        return []
    customer=db.get(User,order.customer_id) if order.customer_id else None
    if not customer:return []
    lines=db.execute(select(OrderItem,Referral,Campaign,Product).join(Referral,Referral.id==OrderItem.referral_id)
        .join(Campaign,Campaign.id==Referral.campaign_id).join(Product,Product.id==OrderItem.product_id)
        .where(OrderItem.order_id==order.id,OrderItem.referral_id.is_not(None)).order_by(OrderItem.id)).all()
    groups={}
    for line,referral,campaign,product in lines:
        ok,_reason=referral_eligibility(db,referral,product,at=order.created_at or datetime.now(timezone.utc))
        if not ok or self_referral(db,referral,customer):
            if self_referral(db,referral,customer):
                flag_risk(db,"SELF_REFERRAL",referral_id=referral.id,conversion_id=conversion.id,customer_id=customer.id,
                    visitor_hash=conversion.visitor_hash,details="Buyer matches the referred creator account/email.")
            continue
        rule,rule_source=select_reward_rule(db,campaign,product,order.created_at or datetime.now(timezone.utc))
        key=(referral.creator_id,campaign.id,rule.id if rule else f"default:{campaign.id}")
        groups.setdefault(key,{"referral":referral,"campaign":campaign,"product":product,"items":[]})["items"].append(line)
    result=[]
    for group in groups.values():
        reward=_record_reward(db,order=order,conversion=conversion,referral=group["referral"],campaign=group["campaign"],
            product=group["product"],lines=group["items"],customer=customer,demo=stage=="demo",stage=stage,actor_id=actor_id)
        if reward:result.append(reward)
    return result


def collect_cod_rewards(db: Session, order: Order, actor_id: int) -> list[Reward]:
    # Called only after the COD collection endpoint atomically marks payment paid
    # and confirms the conversion. Reward rows and ledger credits are created here.
    return generate_order_rewards(db,order,stage="collection",actor_id=actor_id)


def _original_credit(db: Session, reward: Reward):
    return db.scalar(select(LedgerEntry).where(LedgerEntry.reward_id==reward.id,LedgerEntry.direction=="credit").order_by(LedgerEntry.id.asc()))


def _reverse_reward(db: Session, reward: Reward, *, actor_id: int, reason: str, event_key: str):
    if reward.is_demo: raise ValueError("Simulated rewards cannot be reversed as actual financial liabilities")
    order=db.get(Order,reward.order_id)
    conversion=db.scalar(select(Conversion).where(Conversion.order_id==reward.order_id))
    old=reward.status
    credit=_original_credit(db,reward)
    existing_debit=Decimal(db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount),0)).where(LedgerEntry.reward_id==reward.id,LedgerEntry.direction=="debit")) or 0)
    if reward.amount-existing_debit<=0: raise ValueError("Reward liability has already been fully reversed")
    if not credit: raise ValueError("No original ledger credit exists for this reward; manual ledger reconciliation is required")
    remaining=cash(reward.amount-existing_debit)
    reversal=_ledger(db,key=f"reversal:{reward.id}",user_id=reward.creator_id,reward_id=reward.id,order=order,conversion=conversion,
        campaign_id=reward.campaign_id,entry_type="REWARD_REVERSED",amount=remaining,direction="debit",actor_id=actor_id,
        description=f"Reversal: {reason}",reversal_of_id=credit.id)
    if not reversal: raise ValueError("A reversal has already been recorded")
    reward.status="reversed";reward.updated_at=datetime.now(timezone.utc)
    _event(db,reward,event_key,"reward_reversed",old,"reversed",actor_id,reason,{"reversal_entry_id":reversal.id,"amount":str(remaining)})
    return reward


def approve_reward(db: Session, reward: Reward, actor_id: int):
    if reward.is_demo: raise ValueError("Simulated demo rewards cannot be approved or paid")
    if reward.status not in {"pending","under_review"}: raise ValueError("Reward is not awaiting approval")
    if utc(reward.eligible_at)>datetime.now(timezone.utc): raise ValueError("Reward hold period has not elapsed")
    order=db.get(Order,reward.order_id);conversion=db.get(Conversion,reward.conversion_id) if reward.conversion_id else None
    if not order or order.status=="cancelled" or order.payment_status!="paid" or not conversion or conversion.status!="confirmed":
        raise ValueError("Order payment/conversion is not eligible for approval")
    if _reward_has_open_risk(db,reward,conversion.id):
        raise ValueError("Reward has an open risk flag and requires review")
    old=reward.status;reward.status="approved";reward.risk_status="clear";reward.updated_at=datetime.now(timezone.utc)
    _event(db,reward,f"approved:{reward.id}","reward_approved",old,"approved",actor_id,"Administrator approved after hold period.")
    return reward


def reject_reward(db: Session, reward: Reward, actor_id: int, reason: str):
    if reward.is_demo: raise ValueError("Simulated demo rewards cannot enter the payable approval queue")
    if reward.status not in {"pending","under_review"}: raise ValueError("Only pending rewards can be rejected")
    old=reward.status
    credit=_original_credit(db,reward)
    if credit:
        _reverse_reward(db,reward,actor_id=actor_id,reason=reason,event_key=f"rejected:{reward.id}")
        reward.status="rejected"
        _event(db,reward,f"rejected-final:{reward.id}","reward_rejected","reversed","rejected",actor_id,reason)
    else:
        reward.status="rejected";reward.updated_at=datetime.now(timezone.utc)
        _event(db,reward,f"rejected:{reward.id}","reward_rejected",old,"rejected",actor_id,reason)
    return reward


def reverse_reward(db: Session, reward: Reward, actor_id: int, reason: str):
    if reward.status not in {"pending","under_review","approved"}: raise ValueError("Only active non-simulated rewards can be reversed")
    return _reverse_reward(db,reward,actor_id=actor_id,reason=reason,event_key=f"reversed:{reward.id}")


def record_simulated_payout(db: Session, reward: Reward, actor_id: int):
    if reward.status!="approved" or reward.is_demo: raise ValueError("Only approved non-simulated rewards can be recorded in a payout simulation")
    if reward.conversion_id and _reward_has_open_risk(db,reward,reward.conversion_id):
        raise ValueError("Reward has an open risk flag and cannot be recorded in a payout simulation")
    if db.scalar(select(SimulatedPayout.id).where(SimulatedPayout.reward_id==reward.id)):
        raise ValueError("A simulated payout has already been recorded for this reward")
    record=SimulatedPayout(reward_id=reward.id,creator_id=reward.creator_id,amount=reward.amount,currency=reward.currency,
        reference=f"SIM-PAYOUT-{sha256(f'{reward.id}:{actor_id}'.encode()).hexdigest()[:16].upper()}",actor_id=actor_id)
    db.add(record);db.flush()
    order=db.get(Order,reward.order_id);conversion=db.get(Conversion,reward.conversion_id) if reward.conversion_id else None
    if conversion:
        _ledger(db,key=f"simulated-payout:{reward.id}",user_id=reward.creator_id,reward_id=reward.id,order=order,conversion=conversion,
            campaign_id=reward.campaign_id,entry_type="SIMULATED_PAYOUT_RECORDED",amount=reward.amount,direction="memo",actor_id=actor_id,
            description="Simulation only — no actual money was transferred.")
    _event(db,reward,f"simulated-payout:{reward.id}","simulated_payout_recorded",reward.status,reward.status,actor_id,record.disclosure,{"reference":record.reference})
    return record


def cancel_pending_collection_rewards(db: Session, order: Order, actor_id: int):
    rewards=db.scalars(select(Reward).where(Reward.order_id==order.id,Reward.status=="pending_collection")).all()
    for reward in rewards:
        old=reward.status;reward.status="reversed";reward.updated_at=datetime.now(timezone.utc)
        _event(db,reward,f"cancelled:{order.id}:{reward.id}","order_cancelled",old,"reversed",actor_id,"Order cancelled before COD collection; no payable liability was recorded.")
    return rewards
