"""Audited platform administration workflows. All authorization is server-side."""
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.config import settings
from app.models.entities import (AdminAuditEvent, AdminDispute, AdminDisputeEvent, AuthSession, EmailDelivery,
    BrandProfile, Campaign, CampaignProduct, Conversion, CreatorProfile, Order, OrderItem, Product, Referral, ReferralRiskFlag, Reward, User)
from app.security import require_role
from app.api.v1.auth import limiter
from app.services.auth import revoke_sessions
from app.services.notifications import create_notification
from app.services.rewards_engine import hold_reward_for_dispute, release_reward_dispute_hold

router = APIRouter()


def now(): return datetime.now(timezone.utc)


def audit(db: Session, actor: User, action: str, entity_type: str, entity_id: object,
          reason: str, metadata: dict | None = None):
    db.add(AdminAuditEvent(actor_id=actor.id, action=action, entity_type=entity_type,
        entity_id=str(entity_id), reason=reason.strip()[:500], metadata_json=metadata or {}, created_at=now()))


class LifecycleAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    active: bool
    reason: str = Field(min_length=10, max_length=500)
    confirmation: str = Field(min_length=4, max_length=20)

class VerificationAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    status: str = Field(pattern="^(verified|rejected|unverified)$")
    reason: str = Field(min_length=10, max_length=500)
    confirmation: str = Field(min_length=4, max_length=20)

class ModerationAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    status: str = Field(pattern="^(published|paused|rejected)$")
    reason: str = Field(min_length=10, max_length=500)
    confirmation: str = Field(min_length=4, max_length=20)

class ProductModerationAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    status: str = Field(pattern="^(active|inactive)$")
    reason: str = Field(min_length=10, max_length=500)
    confirmation: str = Field(min_length=8, max_length=20)

class RiskAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    status: str = Field(pattern="^(reviewed|dismissed)$")
    reason: str = Field(min_length=10, max_length=500)

class DisputeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    summary: str = Field(min_length=10, max_length=500)
    order_id: int | None = Field(default=None, gt=0)
    conversion_id: int | None = Field(default=None, gt=0)
    reward_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=10, max_length=500)

class UserDisputeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    order_id: str = Field(min_length=6, max_length=40)
    summary: str = Field(min_length=10, max_length=500)
    reason: str = Field(min_length=10, max_length=500)

class DisputeAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    status: str = Field(pattern="^(under_review|resolved)$")
    reason: str = Field(min_length=10, max_length=500)
    confirmation: str = Field(min_length=4, max_length=20)


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return (local[:1] + "***@" + domain) if domain else "hidden"


def _dispute_rewards(db: Session, case: AdminDispute) -> list[Reward]:
    if case.reward_id:
        rows = db.scalars(select(Reward).where(Reward.id == case.reward_id).with_for_update()).all()
    elif case.conversion_id:
        rows = db.scalars(select(Reward).where(Reward.conversion_id == case.conversion_id).order_by(Reward.id).with_for_update()).all()
    elif case.order_id:
        rows = db.scalars(select(Reward).where(Reward.order_id == case.order_id).order_by(Reward.id).with_for_update()).all()
    else:
        rows = []
    return list(rows)


def _hold_dispute_rewards(db: Session, case: AdminDispute, actor_id: int) -> None:
    for reward in _dispute_rewards(db, case):
        hold_reward_for_dispute(db, reward, case.id, actor_id)


def _release_dispute_rewards(db: Session, case: AdminDispute, actor_id: int) -> list[int]:
    released = []
    for reward in _dispute_rewards(db, case):
        if release_reward_dispute_hold(db, reward, case.id, actor_id):
            released.append(reward.id)
    return released


def _notify_dispute_holds(db: Session, case: AdminDispute) -> None:
    for reward in _dispute_rewards(db, case):
        if reward.dispute_hold:
            create_notification(db, recipient_id=reward.creator_id, event_key=f"dispute-hold:{case.id}:{reward.id}",
                category="reward", title="Reward held for dispute review",
                body=f"Reward {reward.id} is on hold while dispute case {case.id} is investigated. Ledger history was preserved.",
                action_path="/earnings")


@router.get("/admin/operations")
@limiter.limit("30/minute")
def operations_overview(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    # DB reachability is tested, but external service health is intentionally not inferred.
    db.scalar(text("SELECT 1"))
    count = lambda stmt: int(db.scalar(stmt) or 0)
    return {
        "service": {"api_liveness": "available", "database_query": "available"},
        "integrations": {"email_delivery": "not_probed", "shared_rate_limit_store": "not_probed", "online_payments": "not_integrated", "payout_transfers": "not_integrated"},
        "queues": {
            "active_users": count(select(func.count(User.id)).where(User.is_active.is_(True))),
            "open_risk_flags": count(select(func.count(ReferralRiskFlag.id)).where(ReferralRiskFlag.status == "open")),
            "open_disputes": count(select(func.count(AdminDispute.id)).where(AdminDispute.status != "resolved")),
            "unverified_creators": count(select(func.count(CreatorProfile.id)).where(CreatorProfile.verification == "unverified")),
            "unverified_brands": count(select(func.count(BrandProfile.id)).where(BrandProfile.verification == "unverified")),
            "campaigns_needing_moderation": count(select(func.count(Campaign.id)).where(Campaign.status == "draft")),
        },
        "notifications": {
            "delivery": "sql_outbox_available",
            "provider": "smtp_configured" if settings.email_mode == "smtp" and settings.smtp_host and settings.email_from else "disabled_or_incomplete",
            "worker_status": "not_measured",
            "pending": count(select(func.count(EmailDelivery.id)).where(EmailDelivery.status == "pending")),
            "failed": count(select(func.count(EmailDelivery.id)).where(EmailDelivery.status == "failed")),
            "suppressed": count(select(func.count(EmailDelivery.id)).where(EmailDelivery.status == "suppressed")),
        },
    }


@router.get("/admin/users")
@limiter.limit("60/minute")
def search_users(request: Request, response: Response, q: str | None = Query(None, max_length=100), role: str | None = Query(None, pattern="^(creator|brand|customer|admin)$"),
                active: bool | None = None, verification: str | None = Query(None, pattern="^(unverified|verified|rejected)$"),
                page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    stmt = select(User)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(term), User.email.ilike(term)))
    if role: stmt = stmt.where(User.role == role)
    if verification:
        stmt = stmt.where(or_(
            (User.role == "creator") & User.id.in_(select(CreatorProfile.user_id).where(CreatorProfile.verification == verification)),
            (User.role == "brand") & User.id.in_(select(BrandProfile.user_id).where(BrandProfile.verification == verification)),
        ))
    if active is not None: stmt = stmt.where(User.is_active.is_(active))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.order_by(User.created_at.desc(), User.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "name": row.name, "email_masked": _mask(row.email), "role": row.role,
        "active": row.is_active, "email_verified": row.email_verified,
        "verification": (db.scalar(select(CreatorProfile.verification).where(CreatorProfile.user_id == row.id)) if row.role == "creator" else
                         db.scalar(select(BrandProfile.verification).where(BrandProfile.user_id == row.id)) if row.role == "brand" else None),
        "created_at": row.created_at.isoformat()} for row in rows], "total": total, "page": page, "page_size": page_size,
        "pages": (total + page_size - 1) // page_size}


@router.post("/admin/users/{user_id}/lifecycle")
@limiter.limit("10/minute")
def change_user_lifecycle(user_id: int, body: LifecycleAction, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    target_role = db.scalar(select(User.role).where(User.id == user_id))
    if target_role is None: raise HTTPException(404, "User not found")
    if target_role == "admin" and not body.active:
        # Lock the admin cohort in stable order before checking the last-admin
        # invariant. Locking only the target allows two admins to suspend each
        # other concurrently on PostgreSQL.
        db.scalars(select(User.id).where(User.role == "admin").order_by(User.id).with_for_update()).all()
    target = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if not target: raise HTTPException(404, "User not found")
    expected = "REACTIVATE" if body.active else "SUSPEND"
    if body.confirmation != expected: raise HTTPException(422, f"Type {expected} to confirm this action")
    if target.id == user.id and not body.active: raise HTTPException(409, "Administrators cannot suspend their own account")
    if target.role == "admin" and not body.active:
        active_admins = db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))) or 0
        if active_admins <= 1: raise HTTPException(409, "The last active administrator cannot be suspended")
    if target.is_active == body.active: raise HTTPException(409, "Account already has the requested state")
    target.is_active = body.active
    if not body.active:
        revoke_sessions(db, target.id)
    lifecycle_audit = AdminAuditEvent(actor_id=user.id, action="user.reactivated" if body.active else "user.suspended",
        entity_type="user", entity_id=str(target.id), reason=body.reason.strip()[:500],
        metadata_json={"active": body.active, "sessions_revoked": not body.active}, created_at=now())
    db.add(lifecycle_audit)
    db.flush()
    notice = ("A CROWND administrator restored access to your account." if body.active else
              "A CROWND administrator suspended access to your account. Contact support if you believe this is a mistake.")
    create_notification(db,recipient_id=target.id,event_key=f"user-lifecycle:{target.id}:{lifecycle_audit.id}",category="security",
        title="Account access updated",body=notice,action_path="/settings/notifications",
        email_subject="Your CROWND account access was updated",email_body=notice,essential_email=True)
    db.commit()
    return {"id": target.id, "active": target.is_active, "sessions_revoked": not body.active}


@router.post("/admin/verification/{role}/{user_id}")
@limiter.limit("10/minute")
def review_verification(role: str, user_id: int, body: VerificationAction, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if role not in {"creator", "brand"}: raise HTTPException(422, "Only creator and brand profiles have manual verification")
    target = db.get(User, user_id)
    if not target or target.role != role: raise HTTPException(404, "Profile not found")
    if body.confirmation != body.status.upper(): raise HTTPException(422, f"Type {body.status.upper()} to confirm this manual review")
    profile = db.scalar(select(CreatorProfile if role == "creator" else BrandProfile).where((CreatorProfile.user_id if role == "creator" else BrandProfile.user_id) == user_id).with_for_update())
    if not profile: raise HTTPException(404, "Profile not found")
    profile.verification = body.status
    audit(db, user, f"{role}.manual_verification.{body.status}", f"{role}_profile", user_id, body.reason,
          {"verification": body.status, "method": "manual_review"})
    db.commit()
    return {"user_id": user_id, "role": role, "verification": profile.verification, "method": "manual_review"}


@router.get("/admin/campaigns")
@limiter.limit("60/minute")
def list_campaigns(request: Request, response: Response, status: str = Query("draft", pattern="^(draft|published|paused|rejected|all)$"), q: str | None = Query(None, max_length=100),
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                  db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    stmt = select(Campaign)
    if status != "all": stmt = stmt.where(Campaign.status == status)
    if q: stmt = stmt.where(or_(Campaign.title.ilike(f"%{q.strip()}%"), Campaign.slug.ilike(f"%{q.strip()}%")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Campaign.created_at.desc(), Campaign.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "title": row.title, "brand_id": row.brand_id, "status": row.status,
        "visibility": row.visibility, "created_at": row.created_at.isoformat()} for row in rows], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


@router.post("/admin/campaigns/{campaign_id}/moderation")
@limiter.limit("10/minute")
def moderate_campaign(campaign_id: int, body: ModerationAction, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
    if not campaign: raise HTTPException(404, "Campaign not found")
    if body.confirmation != body.status.upper(): raise HTTPException(422, f"Type {body.status.upper()} to confirm this moderation action")
    transitions = {"draft": {"published", "rejected"}, "published": {"paused", "rejected"}, "paused": {"published", "rejected"}}
    if body.status not in transitions.get(campaign.status, set()): raise HTTPException(409, "Invalid moderation transition")
    previous = campaign.status
    campaign.status = body.status
    audit(db, user, f"campaign.moderation.{body.status}", "campaign", campaign.id, body.reason,
          {"from_status": previous, "to_status": body.status})
    notice = f"Your campaign moderation status was updated to {body.status}. The platform status is recorded for review and publishing."
    create_notification(db,recipient_id=campaign.brand_id,event_key=f"campaign-moderated:{campaign.id}:{uuid4().hex}",category="campaign",
        title="Campaign moderation update",body=notice,action_path="/brand/campaigns",
        email_subject="Campaign moderation update",email_body=notice)
    db.commit()
    return {"id": campaign.id, "from_status": previous, "status": campaign.status}


@router.get("/admin/products")
@limiter.limit("60/minute")
def list_products(request: Request, response: Response, q: str | None = Query(None, max_length=120), status: str = Query("all", pattern="^(active|inactive|all)$"), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    stmt = select(Product)
    if status != "all": stmt = stmt.where(Product.status == status)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(term), Product.slug.ilike(term)))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.order_by(Product.created_at.desc(), Product.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "brand_id": row.brand_id, "name": row.name, "slug": row.slug, "status": row.status, "stock": row.stock, "price": str(row.price), "created_at": row.created_at.isoformat()} for row in rows], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


@router.post("/admin/products/{product_id}/moderation")
@limiter.limit("10/minute")
def moderate_product(product_id: int, body: ProductModerationAction, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not product: raise HTTPException(404, "Product not found")
    expected = "ACTIVATE" if body.status == "active" else "DEACTIVATE"
    if body.confirmation != expected: raise HTTPException(422, f"Type {expected} to confirm this moderation action")
    if product.status == body.status: raise HTTPException(409, "Product already has the requested status")
    if body.status == "inactive":
        linked = db.scalar(select(Campaign.id).outerjoin(CampaignProduct, CampaignProduct.campaign_id == Campaign.id).where(
            Campaign.status == "published", or_(Campaign.product_id == product.id, CampaignProduct.product_id == product.id)
        ).limit(1))
        if linked: raise HTTPException(409, "Pause or complete linked published campaigns before deactivating this product")
    previous = product.status
    product.status = body.status
    audit(db, user, f"product.moderation.{body.status}", "product", product.id, body.reason,
          {"brand_id": product.brand_id, "from_status": previous, "to_status": body.status})
    db.commit()
    return {"id": product.id, "from_status": previous, "status": product.status}


@router.get("/disputes")
@limiter.limit("60/minute")
def list_user_disputes(request: Request, response: Response, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_role("customer", "creator", "brand"))):
    stmt = select(AdminDispute).where(AdminDispute.opened_by == user.id)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    cases = db.scalars(stmt.order_by(AdminDispute.created_at.desc(), AdminDispute.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": case.id, "order_id": db.get(Order, case.order_id).public_id if case.order_id and db.get(Order, case.order_id) else None,
        "summary": case.summary, "status": case.status, "created_at": case.created_at.isoformat(),
        "events": [{"event_type": event.event_type, "from_status": event.from_status, "to_status": event.to_status,
                    "reason": event.reason, "created_at": event.created_at.isoformat()} for event in db.scalars(select(AdminDisputeEvent).where(AdminDisputeEvent.dispute_id == case.id).order_by(AdminDisputeEvent.id)).all()]}
        for case in cases], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


@router.post("/disputes", status_code=201)
@limiter.limit("5/hour")
def open_user_dispute(body: UserDisputeCreate, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("customer", "creator", "brand"))):
    order = db.scalar(select(Order).where(Order.public_id == body.order_id).with_for_update())
    if not order:
        raise HTTPException(404, "Order not found")
    owns = order.customer_id == user.id or (user.role == "customer" and order.customer_email.lower() == user.email.lower())
    if user.role == "brand":
        product_ids = set(db.scalars(select(OrderItem.product_id).where(OrderItem.order_id == order.id, OrderItem.product_id.is_not(None))).all())
        if order.product_id:
            product_ids.add(order.product_id)
        owns = bool(product_ids and db.scalar(select(Product.id).where(Product.id.in_(product_ids), Product.brand_id == user.id).limit(1)))
    elif user.role == "creator" and order.referral_id:
        referral = db.get(Referral, order.referral_id)
        owns = owns or bool(referral and referral.creator_id == user.id)
    if not owns:
        raise HTTPException(404, "Order not found")
    existing = db.scalar(select(AdminDispute).where(AdminDispute.order_id == order.id, AdminDispute.opened_by == user.id,
        AdminDispute.status.in_(["open", "under_review"])).with_for_update())
    if existing:
        raise HTTPException(409, f"An open dispute already exists for this order (case {existing.id})")
    conversion = db.scalar(select(Conversion).where(Conversion.order_id == order.id))
    case = AdminDispute(order_id=order.id, conversion_id=conversion.id if conversion else None,
        status="open", summary=body.summary, opened_by=user.id, created_at=now())
    db.add(case); db.flush()
    _hold_dispute_rewards(db, case, user.id)
    _notify_dispute_holds(db, case)
    db.add(AdminDisputeEvent(dispute_id=case.id, actor_id=user.id, event_type="opened", from_status=None, to_status="open", reason=body.reason, created_at=now()))
    audit(db, user, "dispute.opened_by_user", "dispute", case.id, body.reason, {"order_id": order.id, "conversion_id": case.conversion_id, "reporter_role": user.role})
    for administrator in db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all():
        create_notification(db, recipient_id=administrator.id, event_key=f"dispute-user-opened:{case.id}:{administrator.id}", category="order",
            title="A customer dispute was opened", body="A platform participant submitted an order dispute for administrator review.",
            action_path="/admin/disputes")
    db.commit()
    return {"id": case.id, "order_id": order.public_id, "status": case.status, "financial_history_mutated": False}


@router.get("/admin/disputes")
@limiter.limit("60/minute")
def list_disputes(request: Request, response: Response, status: str = Query("open", pattern="^(open|under_review|resolved|all)$"), page: int = Query(1, ge=1),
                  page_size: int = Query(25, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    stmt = select(AdminDispute)
    if status != "all": stmt = stmt.where(AdminDispute.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    cases = db.scalars(stmt.order_by(AdminDispute.created_at.desc(), AdminDispute.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "order_id": row.order_id, "conversion_id": row.conversion_id, "reward_id": row.reward_id,
        "status": row.status, "summary": row.summary, "created_at": row.created_at.isoformat(),
        "events": [{"event_type": event.event_type, "from_status": event.from_status, "to_status": event.to_status,
                    "reason": event.reason, "created_at": event.created_at.isoformat()} for event in db.scalars(select(AdminDisputeEvent).where(AdminDisputeEvent.dispute_id == row.id).order_by(AdminDisputeEvent.id)).all()]}
        for row in cases], "total": total, "page": page, "page_size": page_size}


@router.post("/admin/disputes", status_code=201)
@limiter.limit("10/minute")
def create_dispute(body: DisputeCreate, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if not any((body.order_id, body.conversion_id, body.reward_id)): raise HTTPException(422, "Link the case to an order, conversion, or reward")
    order = db.get(Order, body.order_id) if body.order_id else None
    conversion = db.get(Conversion, body.conversion_id) if body.conversion_id else None
    reward = db.get(Reward, body.reward_id) if body.reward_id else None
    if body.order_id and not order: raise HTTPException(404, "Order not found")
    if body.conversion_id and not conversion: raise HTTPException(404, "Conversion not found")
    if body.reward_id and not reward: raise HTTPException(404, "Reward not found")
    if order and conversion and conversion.order_id != order.id:
        raise HTTPException(422, "Order and conversion must refer to the same order")
    if order and reward and reward.order_id != order.id:
        raise HTTPException(422, "Order and reward must refer to the same order")
    if conversion and reward and reward.conversion_id != conversion.id:
        raise HTTPException(422, "Conversion and reward must refer to the same conversion")
    case = AdminDispute(order_id=body.order_id, conversion_id=body.conversion_id, reward_id=body.reward_id,
        status="open", summary=body.summary, opened_by=user.id, created_at=now())
    db.add(case); db.flush()
    _hold_dispute_rewards(db, case, user.id)
    db.add(AdminDisputeEvent(dispute_id=case.id, actor_id=user.id, event_type="opened", from_status=None,
        to_status="open", reason=body.reason, created_at=now()))
    audit(db, user, "dispute.opened", "dispute", case.id, body.reason, {"order_id": body.order_id,
        "conversion_id": body.conversion_id, "reward_id": body.reward_id})
    _notify_dispute_holds(db, case)
    db.commit()
    return {"id": case.id, "status": case.status, "financial_history_mutated": False}


@router.post("/admin/disputes/{dispute_id}/status")
@limiter.limit("10/minute")
def update_dispute(dispute_id: int, body: DisputeAction, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    case = db.scalar(select(AdminDispute).where(AdminDispute.id == dispute_id).with_for_update())
    if not case: raise HTTPException(404, "Dispute not found")
    if body.confirmation != body.status.upper(): raise HTTPException(422, f"Type {body.status.upper()} to confirm this case action")
    allowed = {"open": {"under_review", "resolved"}, "under_review": {"resolved"}, "resolved": set()}
    if body.status not in allowed[case.status]: raise HTTPException(409, "Invalid dispute transition")
    previous = case.status; case.status = body.status
    if body.status == "resolved": case.resolved_by = user.id; case.resolved_at = now()
    # Release checks query other active disputes, so make this transition visible
    # even for sessions configured with autoflush disabled.
    db.flush()
    db.add(AdminDisputeEvent(dispute_id=case.id, actor_id=user.id, event_type="status_changed", from_status=previous,
        to_status=body.status, reason=body.reason, created_at=now()))
    audit(db, user, f"dispute.{body.status}", "dispute", case.id, body.reason, {"from_status": previous, "to_status": body.status})
    released_rewards = _release_dispute_rewards(db, case, user.id) if body.status == "resolved" else []
    order = db.get(Order, case.order_id) if case.order_id else None
    recipients = {case.opened_by} if case.opened_by and case.opened_by != user.id else set()
    for reward in _dispute_rewards(db, case):
        recipients.add(reward.creator_id)
        if reward.id in released_rewards:
            create_notification(db, recipient_id=reward.creator_id, event_key=f"dispute-release:{case.id}:{reward.id}",
                category="reward", title="Reward dispute hold updated",
                body=f"Dispute case {case.id} was resolved. The reward review state was restored when no other open dispute or risk hold remained. Ledger history was preserved.",
                action_path="/earnings")
    for recipient_id in recipients:
        create_notification(db, recipient_id=recipient_id, event_key=f"dispute-status:{case.id}:{body.status}:{recipient_id}", category="order",
            title="Order issue status updated", body=f"Your dispute case is now {body.status.replace('_', ' ')}. The decision did not delete or overwrite financial history.",
            action_path=f"/orders/{order.public_id}" if order else None)
    db.commit()
    return {"id": case.id, "status": case.status, "financial_history_mutated": False, "released_rewards": released_rewards}


@router.get("/admin/audit-events")
@limiter.limit("60/minute")
def list_admin_audit_events(request: Request, response: Response, action: str | None = Query(None, max_length=100), entity_type: str | None = Query(None, max_length=60),
                           page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                           db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    stmt = select(AdminAuditEvent)
    if action: stmt = stmt.where(AdminAuditEvent.action == action)
    if entity_type: stmt = stmt.where(AdminAuditEvent.entity_type == entity_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AdminAuditEvent.created_at.desc(), AdminAuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "actor_id": row.actor_id, "action": row.action, "entity_type": row.entity_type,
        "entity_id": row.entity_id, "reason": row.reason, "metadata": row.metadata_json, "created_at": row.created_at.isoformat()} for row in rows],
        "total": total, "page": page, "page_size": page_size}
