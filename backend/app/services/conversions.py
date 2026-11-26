"""Order-backed referral conversion ledger and explainable risk flags."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.entities import Conversion, ConversionEvent, Order, Referral, ReferralRiskFlag, User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def flag_risk(db: Session, risk_code: str, *, referral_id: int | None = None, conversion_id: int | None = None, customer_id: int | None = None, visitor_hash: str | None = None, details: str = "") -> ReferralRiskFlag:
    cutoff = utcnow() - timedelta(days=1)
    stmt = select(ReferralRiskFlag.id).where(ReferralRiskFlag.risk_code == risk_code, ReferralRiskFlag.status == "open", ReferralRiskFlag.created_at >= cutoff)
    stmt = stmt.where(ReferralRiskFlag.referral_id == referral_id) if referral_id is not None else stmt.where(ReferralRiskFlag.referral_id.is_(None))
    stmt = stmt.where(ReferralRiskFlag.customer_id == customer_id) if customer_id is not None else stmt.where(ReferralRiskFlag.customer_id.is_(None))
    stmt = stmt.where(ReferralRiskFlag.visitor_hash == visitor_hash) if visitor_hash else stmt.where(ReferralRiskFlag.visitor_hash.is_(None))
    if not db.scalar(stmt):
        row = ReferralRiskFlag(risk_code=risk_code, referral_id=referral_id, conversion_id=conversion_id, customer_id=customer_id, visitor_hash=visitor_hash, details=details[:240])
        db.add(row)
        db.flush()
        return row
    return db.scalar(select(ReferralRiskFlag).where(ReferralRiskFlag.risk_code == risk_code, ReferralRiskFlag.status == "open").order_by(ReferralRiskFlag.created_at.desc()))


def create_conversion(db: Session, order: Order, referral: Referral, *, visitor_hash: str | None, attributed_amount: Decimal, eligible_product_count: int, customer: User, self_referral_only: bool | None = None) -> Conversion:
    existing = db.scalar(select(Conversion).where(Conversion.order_id == order.id))
    if existing:
        return existing
    creator = db.get(User, referral.creator_id)
    reason = None
    status = "pending"
    amount = Decimal(attributed_amount).quantize(Decimal("0.01"))
    matches_creator = bool(creator and (creator.id == customer.id or creator.email.strip().casefold() == customer.email.strip().casefold()))
    self_only = matches_creator if self_referral_only is None else self_referral_only
    if self_only:
        status, reason, amount = "ineligible", "self_referral", Decimal("0.00")
    elif eligible_product_count <= 0 or amount <= 0:
        status, reason, amount = "ineligible", "no_eligible_products", Decimal("0.00")
    conversion = Conversion(order_id=order.id, referral_id=referral.id, creator_id=referral.creator_id, campaign_id=referral.campaign_id, visitor_hash=visitor_hash, status=status, attributed_amount=amount, currency=order.currency or "INR", is_demo=order.payment_method == "demo", reason=reason)
    db.add(conversion)
    db.flush()
    db.add(ConversionEvent(conversion_id=conversion.id, event_key=f"created:{order.id}", event_type="order_created", from_status=None, to_status=status, reason=reason))
    if reason == "self_referral":
        flag_risk(db, "SELF_REFERRAL", referral_id=referral.id, conversion_id=conversion.id, customer_id=customer.id, visitor_hash=visitor_hash, details="Buyer matches the referred creator account/email.")
    elif reason == "no_eligible_products":
        flag_risk(db, "INELIGIBLE_CAMPAIGN", referral_id=referral.id, conversion_id=conversion.id, customer_id=customer.id, visitor_hash=visitor_hash, details="Order contained no product eligible for this campaign link.")
    previous = db.scalar(select(func.count(Conversion.id)).join(Order, Order.id == Conversion.order_id).where(Conversion.creator_id == referral.creator_id, Order.customer_id == customer.id, Conversion.order_id != order.id, Conversion.created_at >= utcnow() - timedelta(days=7)))
    if previous:
        flag_risk(db, "REPEATED_CUSTOMER_PATTERN", referral_id=referral.id, conversion_id=conversion.id, customer_id=customer.id, visitor_hash=visitor_hash, details="Customer has multiple attributed orders within seven days; review only, not an automatic block.")
    return conversion


def transition_conversion(db: Session, conversion: Conversion | None, target: str, *, event_key: str, event_type: str, actor_id: int | None = None, reason: str | None = None) -> Conversion | None:
    if conversion is None:
        return None
    existing = db.scalar(select(ConversionEvent.id).where(ConversionEvent.conversion_id == conversion.id, ConversionEvent.event_key == event_key))
    if existing:
        return conversion
    allowed = {"pending": {"confirmed", "cancelled", "ineligible"}, "confirmed": {"reversed", "cancelled"}, "cancelled": set(), "reversed": set(), "ineligible": set()}
    if target == conversion.status:
        return conversion
    if target not in allowed.get(conversion.status, set()):
        return conversion
    old = conversion.status
    conversion.status = target
    conversion.reason = reason
    if target == "confirmed":
        conversion.confirmed_at = utcnow()
    conversion.updated_at = utcnow()
    db.add(ConversionEvent(conversion_id=conversion.id, event_key=event_key, event_type=event_type, from_status=old, to_status=target, actor_id=actor_id, reason=reason))
    return conversion
