"""Transactional notification creation and a small encrypted SQL mail outbox."""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import AuthActionToken, EmailDelivery, Notification, NotificationPreference, User
from app.services.email import EmailDeliveryError, OutgoingEmail, get_email_provider

CATEGORIES = ("order", "campaign", "application", "reward", "security", "account")
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (60, 300, 900, 3600)
CLAIM_TIMEOUT = timedelta(minutes=10)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fernet() -> Fernet:
    # The existing high-entropy JWT secret is the deployment secret source. A dedicated
    # key rotation requires draining/decrypting queued rows before replacing JWT_SECRET.
    key = base64.urlsafe_b64encode(sha256(("crownd-email-outbox:" + settings.jwt_secret).encode()).digest())
    return Fernet(key)


def encrypt_email(message: OutgoingEmail) -> str:
    payload = json.dumps({"subject": message.subject, "text": message.text}, separators=(",", ":"))
    return _fernet().encrypt(payload.encode()).decode()


def decrypt_email(ciphertext: str, recipient: str) -> OutgoingEmail:
    payload = json.loads(_fernet().decrypt(ciphertext.encode()).decode())
    return OutgoingEmail(to=recipient, subject=payload["subject"], text=payload["text"])


def _safe_header(value: str, limit: int) -> str:
    value = value.strip()
    if not value or len(value) > limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Invalid notification email content")
    return value


def _safe_text(value: str, limit: int) -> str:
    value = value.strip()
    if not value or len(value) > limit or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("Invalid notification content")
    return value


def _safe_path(path: str | None) -> str | None:
    if path is None:
        return None
    allowed = {"/applications", "/earnings", "/brand/campaigns", "/settings/notifications", "/admin/disputes"}
    if path not in allowed and not re.fullmatch(r"/orders/[A-Za-z0-9-]{1,80}", path):
        raise ValueError("Notification action must be a supported internal route")
    return path


def get_or_create_preferences(db: Session, user_id: int) -> NotificationPreference:
    row = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    if row:
        return row
    row = NotificationPreference(user_id=user_id, in_app_enabled=True, email_enabled=True, category_settings={})
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        existing = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
        if existing is None:
            raise
        return existing


def _enabled(preferences: NotificationPreference, category: str, channel: str) -> bool:
    override = (preferences.category_settings or {}).get(category, {})
    return bool(override.get(channel, getattr(preferences, f"{channel}_enabled")))


def _insert_idempotently(db: Session, row) -> bool:
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return True
    except IntegrityError:
        return False


def enqueue_email(db: Session, user_id: int, event_key: str, category: str,
                  message: OutgoingEmail, *, essential: bool = False) -> bool:
    if category not in CATEGORIES:
        raise ValueError("Unsupported notification category")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", event_key):
        raise ValueError("Invalid notification idempotency key")
    subject = _safe_header(message.subject, 160)
    text = _safe_text(message.text, 4000)
    if not essential:
        preferences = get_or_create_preferences(db, user_id)
        if not _enabled(preferences, category, "email"):
            return False
    row = EmailDelivery(recipient_id=user_id, event_key=event_key, category=category,
                        essential=essential, encrypted_message=encrypt_email(OutgoingEmail("queued", subject, text)),
                        status="pending", attempt_count=0, next_attempt_at=utcnow(), created_at=utcnow())
    return _insert_idempotently(db, row)


def create_notification(db: Session, *, recipient_id: int, event_key: str, category: str,
                        title: str, body: str, action_path: str | None = None,
                        email_subject: str | None = None, email_body: str | None = None,
                        essential_email: bool = False) -> bool:
    if category not in CATEGORIES:
        raise ValueError("Unsupported notification category")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", event_key):
        raise ValueError("Invalid notification idempotency key")
    title = _safe_text(title, 160)
    body = _safe_text(body, 1000)
    action_path = _safe_path(action_path)
    preferences = get_or_create_preferences(db, recipient_id)
    created = False
    if _enabled(preferences, category, "in_app"):
        created = _insert_idempotently(db, Notification(recipient_id=recipient_id, event_key=event_key,
            category=category, title=title, body=body, action_path=action_path, created_at=utcnow()))
    if email_subject is not None and email_body is not None and (essential_email or _enabled(preferences, category, "email")):
        enqueue_email(db, recipient_id, event_key, category,
                      OutgoingEmail(to="queued", subject=email_subject, text=email_body), essential=essential_email)
    return created


def enqueue_action_email(db: Session, user: User, purpose: str, token: str, frontend_base_url: str) -> bool:
    if purpose == "verify_email":
        subject = "Verify your CROWND email"
        path = "/verify-email"
        description = "Confirm your email address to finish creating your CROWND account."
        category = "account"
        expiry = "This link expires soon and can only be used once."
    elif purpose == "password_reset":
        subject = "Reset your CROWND password"
        path = "/reset-password"
        description = "Use this one-time link to set a new CROWND password. If you did not request this, ignore this email."
        category = "security"
        expiry = "This link expires soon and can only be used once."
    else:
        raise ValueError("Unsupported account email purpose")
    # Use the existing token record ID for durable idempotency; never place the
    # raw token or a token-derived digest in an outbox key or admin response.
    db.flush()
    token_hash = sha256(token.encode()).hexdigest()
    token_record = db.scalar(select(AuthActionToken).where(AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == purpose, AuthActionToken.token_hash == token_hash).order_by(AuthActionToken.id.desc()))
    if token_record is None:
        raise ValueError("Action token was not persisted in the current transaction")
    # Fragment tokens are not transmitted to the web server or access logs.
    link = f"{frontend_base_url.rstrip('/')}{path}#token={token}"
    return enqueue_email(db, user.id, f"auth:{purpose}:{token_record.id}", category,
                         OutgoingEmail(to=user.email, subject=subject,
                                       text=f"{description}\n\n{link}\n\n{expiry}"), essential=True)


def _claim_one(db: Session, now: datetime) -> EmailDelivery | None:
    db.execute(update(EmailDelivery).where(EmailDelivery.status == "sending",
        EmailDelivery.claimed_at < now - CLAIM_TIMEOUT).values(status="pending", claimed_at=None,
        next_attempt_at=now, last_error_code="worker_interrupted").execution_options(synchronize_session=False))
    row = db.scalar(select(EmailDelivery).where(EmailDelivery.status == "pending",
        EmailDelivery.next_attempt_at <= now).order_by(EmailDelivery.next_attempt_at, EmailDelivery.id).limit(1))
    if not row:
        db.commit()
        return None
    claimed = db.execute(update(EmailDelivery).where(EmailDelivery.id == row.id,
        EmailDelivery.status == "pending", EmailDelivery.next_attempt_at <= now).values(
            status="sending", claimed_at=now, attempt_count=EmailDelivery.attempt_count + 1).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        db.rollback()
        return None
    delivery_id = row.id
    db.commit()
    db.expire_all()
    return db.get(EmailDelivery, delivery_id)


def deliver_one(db: Session, *, now: datetime | None = None) -> bool:
    """Deliver one due row. One worker process is supported; multi-process locking is unverified."""
    moment = now or utcnow()
    delivery = _claim_one(db, moment)
    if delivery is None:
        return False
    recipient = db.get(User, delivery.recipient_id)
    if not recipient or (not delivery.essential and (not recipient.is_active or not recipient.email_verified)):
        delivery.status = "suppressed"
        delivery.last_error_code = "recipient_unavailable"
        delivery.claimed_at = None
        db.commit()
        return True
    if settings.email_mode != "smtp":
        delivery.status = "suppressed"
        delivery.last_error_code = "provider_disabled"
        delivery.claimed_at = None
        db.commit()
        return True
    try:
        message = decrypt_email(delivery.encrypted_message, recipient.email)
        accepted = get_email_provider().send(message)
        if not accepted:
            delivery.status = "suppressed"
            delivery.last_error_code = "provider_disabled"
        else:
            delivery.status = "sent"
            delivery.delivered_at = utcnow()
            delivery.last_error_code = None
        delivery.claimed_at = None
        db.commit()
    except (InvalidToken, ValueError, KeyError, json.JSONDecodeError):
        delivery.status = "failed"
        delivery.last_error_code = "payload_unavailable"
        delivery.claimed_at = None
        db.commit()
    except EmailDeliveryError as exc:
        delivery.claimed_at = None
        allowed_codes = {"provider_error", "provider_misconfigured", "payload_invalid", "provider_authentication",
            "recipient_temporary", "recipient_rejected", "provider_temporary", "provider_rejected", "provider_transient"}
        delivery.last_error_code = exc.category if exc.category in allowed_codes else "provider_error"
        if not exc.retryable or delivery.attempt_count >= MAX_ATTEMPTS:
            delivery.status = "failed"
        else:
            delivery.status = "pending"
            delivery.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_SECONDS[min(delivery.attempt_count - 1, len(BACKOFF_SECONDS) - 1)])
        db.commit()
    except Exception:
        # Provider details, destination and message content are deliberately never persisted.
        delivery.claimed_at = None
        delivery.last_error_code = "provider_error"
        if delivery.attempt_count >= MAX_ATTEMPTS:
            delivery.status = "failed"
        else:
            delivery.status = "pending"
            delivery.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_SECONDS[min(delivery.attempt_count - 1, len(BACKOFF_SECONDS) - 1)])
        db.commit()
    return True


def process_due_deliveries(db: Session, *, batch_size: int = 20) -> int:
    if not 1 <= batch_size <= 100:
        raise ValueError("Worker batch size must be between 1 and 100")
    count = 0
    for _ in range(batch_size):
        if not deliver_one(db):
            break
        count += 1
    return count
