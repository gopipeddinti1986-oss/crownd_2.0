"""Recipient-scoped inbox, preferences, and admin-only delivery telemetry."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.models.entities import EmailDelivery, Notification, NotificationPreference, User
from app.security import current_user, require_role
from app.api.v1.auth import limiter
from app.services.notifications import CATEGORIES, get_or_create_preferences

router = APIRouter()


class CategoryChannels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_app: bool = True
    email: bool = True


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_app_enabled: bool = True
    email_enabled: bool = True
    category_settings: dict[str, CategoryChannels] = Field(default_factory=dict)

    @field_validator("category_settings")
    @classmethod
    def valid_categories(cls, value):
        if set(value) - set(CATEGORIES):
            raise ValueError("Unsupported notification category")
        return value


def _preferences_payload(row: NotificationPreference) -> dict:
    settings_by_category = row.category_settings or {}
    return {"in_app_enabled": row.in_app_enabled, "email_enabled": row.email_enabled,
        "category_settings": {category: channels for category, channels in settings_by_category.items() if category in CATEGORIES},
        "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.get("/notifications")
@limiter.limit("60/minute")
def list_notifications(request: Request, response: Response, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      unread_only: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Notification).where(Notification.recipient_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery()) ) or 0)
    unread = int(db.scalar(select(func.count(Notification.id)).where(
        Notification.recipient_id == user.id, Notification.read_at.is_(None))) or 0)
    rows = db.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "category": row.category, "title": row.title, "body": row.body,
        "action_path": row.action_path, "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat()} for row in rows], "total": total,
        "unread_count": unread, "page": page, "page_size": page_size,
        "pages": (total + page_size - 1) // page_size}


@router.patch("/notifications/{notification_id}/read")
@limiter.limit("30/minute")
def mark_notification_read(notification_id: int, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Notification).where(Notification.id == notification_id,
        Notification.recipient_id == user.id))
    if not row:
        raise HTTPException(404, "Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()
    return {"id": row.id, "read_at": row.read_at.isoformat()}


@router.post("/notifications/read-all")
@limiter.limit("10/minute")
def mark_all_notifications_read(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    result = db.execute(update(Notification).where(Notification.recipient_id == user.id,
        Notification.read_at.is_(None)).values(read_at=datetime.now(timezone.utc)))
    db.commit()
    return {"updated": result.rowcount or 0}


@router.get("/notifications/preferences")
@limiter.limit("60/minute")
def get_notification_preferences(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id))
    if not row:
        return {"in_app_enabled": True, "email_enabled": True, "category_settings": {}, "updated_at": None}
    return _preferences_payload(row)


@router.put("/notifications/preferences")
@limiter.limit("10/minute")
def update_notification_preferences(body: PreferencesUpdate, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = get_or_create_preferences(db, user.id)
    row.in_app_enabled = body.in_app_enabled
    row.email_enabled = body.email_enabled
    row.category_settings = {category: setting.model_dump() for category, setting in body.category_settings.items()}
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _preferences_payload(row)


@router.get("/admin/notification-deliveries/summary")
@limiter.limit("30/minute")
def notification_delivery_summary(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    grouped = dict(db.execute(select(EmailDelivery.status, func.count(EmailDelivery.id)).group_by(EmailDelivery.status)).all())
    latest = db.scalar(select(func.max(EmailDelivery.created_at)))
    provider_configured = bool(settings.email_mode == "smtp" and settings.smtp_host and settings.email_from)
    return {"counts": {status: int(grouped.get(status, 0)) for status in
            ("pending", "sending", "sent", "suppressed", "failed")},
        "provider": "smtp_configured" if provider_configured else "disabled_or_incomplete",
        "worker_status": "not_measured", "latest_queued_at": latest.isoformat() if latest else None,
        "delivery_semantics": "at_least_once; provider acceptance does not guarantee inbox delivery"}


@router.get("/admin/notification-deliveries")
@limiter.limit("60/minute")
def list_notification_deliveries(request: Request, response: Response, status: str | None = Query(None, pattern="^(pending|sending|sent|suppressed|failed)$"),
                                 category: str | None = Query(None, pattern="^(order|campaign|application|reward|security|account)$"),
                                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                                 db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    stmt = select(EmailDelivery)
    if status:
        stmt = stmt.where(EmailDelivery.status == status)
    if category:
        stmt = stmt.where(EmailDelivery.category == category)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.order_by(EmailDelivery.created_at.desc(), EmailDelivery.id.desc())
        .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "category": row.category, "status": row.status,
        "attempt_count": row.attempt_count, "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "last_error_code": row.last_error_code, "created_at": row.created_at.isoformat(),
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None}
        for row in rows], "total": total, "page": page, "page_size": page_size,
        "pages": (total + page_size - 1) // page_size}
