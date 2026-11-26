"""Audited platform administration workflows. All authorization is server-side."""
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.entities import (AdminAuditEvent, AdminDispute, AdminDisputeEvent, AuthSession,
    BrandProfile, Campaign, Conversion, CreatorProfile, Order, ReferralRiskFlag, Reward, User)
from app.security import require_role
from app.services.auth import revoke_sessions

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

class DisputeAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    status: str = Field(pattern="^(under_review|resolved)$")
    reason: str = Field(min_length=10, max_length=500)
    confirmation: str = Field(min_length=4, max_length=20)


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return (local[:1] + "***@" + domain) if domain else "hidden"


@router.get("/admin/operations")
def operations_overview(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
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
        "notifications": {"delivery": "unavailable", "reason": "No persisted notification or delivery provider is configured."},
    }


@router.get("/admin/users")
def search_users(q: str | None = Query(None, max_length=100), role: str | None = Query(None, pattern="^(creator|brand|customer|admin)$"),
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
def change_user_lifecycle(user_id: int, body: LifecycleAction, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    target = db.scalar(select(User).where(User.id == user_id).with_for_update())
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
    audit(db, user, "user.reactivated" if body.active else "user.suspended", "user", target.id, body.reason,
          {"active": body.active, "sessions_revoked": not body.active})
    db.commit()
    return {"id": target.id, "active": target.is_active, "sessions_revoked": not body.active}


@router.post("/admin/verification/{role}/{user_id}")
def review_verification(role: str, user_id: int, body: VerificationAction, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
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
def list_campaigns(status: str = Query("draft", pattern="^(draft|published|paused|rejected|all)$"), q: str | None = Query(None, max_length=100),
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
def moderate_campaign(campaign_id: int, body: ModerationAction, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
    if not campaign: raise HTTPException(404, "Campaign not found")
    if body.confirmation != body.status.upper(): raise HTTPException(422, f"Type {body.status.upper()} to confirm this moderation action")
    transitions = {"draft": {"published", "rejected"}, "published": {"paused", "rejected"}, "paused": {"published", "rejected"}}
    if body.status not in transitions.get(campaign.status, set()): raise HTTPException(409, "Invalid moderation transition")
    previous = campaign.status
    campaign.status = body.status
    audit(db, user, f"campaign.moderation.{body.status}", "campaign", campaign.id, body.reason,
          {"from_status": previous, "to_status": body.status})
    db.commit()
    return {"id": campaign.id, "from_status": previous, "status": campaign.status}


@router.get("/admin/disputes")
def list_disputes(status: str = Query("open", pattern="^(open|under_review|resolved|all)$"), page: int = Query(1, ge=1),
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
def create_dispute(body: DisputeCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if not any((body.order_id, body.conversion_id, body.reward_id)): raise HTTPException(422, "Link the case to an order, conversion, or reward")
    if body.order_id and not db.get(Order, body.order_id): raise HTTPException(404, "Order not found")
    if body.conversion_id and not db.get(Conversion, body.conversion_id): raise HTTPException(404, "Conversion not found")
    if body.reward_id and not db.get(Reward, body.reward_id): raise HTTPException(404, "Reward not found")
    case = AdminDispute(order_id=body.order_id, conversion_id=body.conversion_id, reward_id=body.reward_id,
        status="open", summary=body.summary, opened_by=user.id, created_at=now())
    db.add(case); db.flush()
    db.add(AdminDisputeEvent(dispute_id=case.id, actor_id=user.id, event_type="opened", from_status=None,
        to_status="open", reason=body.reason, created_at=now()))
    audit(db, user, "dispute.opened", "dispute", case.id, body.reason, {"order_id": body.order_id,
        "conversion_id": body.conversion_id, "reward_id": body.reward_id})
    db.commit()
    return {"id": case.id, "status": case.status, "financial_history_mutated": False}


@router.post("/admin/disputes/{dispute_id}/status")
def update_dispute(dispute_id: int, body: DisputeAction, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    case = db.scalar(select(AdminDispute).where(AdminDispute.id == dispute_id).with_for_update())
    if not case: raise HTTPException(404, "Dispute not found")
    if body.confirmation != body.status.upper(): raise HTTPException(422, f"Type {body.status.upper()} to confirm this case action")
    allowed = {"open": {"under_review", "resolved"}, "under_review": {"resolved"}, "resolved": set()}
    if body.status not in allowed[case.status]: raise HTTPException(409, "Invalid dispute transition")
    previous = case.status; case.status = body.status
    if body.status == "resolved": case.resolved_by = user.id; case.resolved_at = now()
    db.add(AdminDisputeEvent(dispute_id=case.id, actor_id=user.id, event_type="status_changed", from_status=previous,
        to_status=body.status, reason=body.reason, created_at=now()))
    audit(db, user, f"dispute.{body.status}", "dispute", case.id, body.reason, {"from_status": previous, "to_status": body.status})
    db.commit()
    return {"id": case.id, "status": case.status, "financial_history_mutated": False}


@router.get("/admin/audit-events")
def list_admin_audit_events(action: str | None = Query(None, max_length=100), entity_type: str | None = Query(None, max_length=60),
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
