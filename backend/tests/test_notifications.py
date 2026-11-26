from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.auth import limiter
from app.core.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.entities import AuthActionToken, EmailDelivery, Notification, NotificationPreference, User
from app.security import create_access_token
from app.services.auth import create_session
from app.services.email import EmailDeliveryError
from app.services.notifications import create_notification, decrypt_email, enqueue_action_email, process_due_deliveries, utcnow


@pytest.fixture
def notification_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    limiter.reset()
    with TestClient(app) as client:
        def account(name, role="customer"):
            with factory() as db:
                user = User(name=name, email=f"{name.lower()}@example.test", role=role,
                    password_hash="not-used", email_verified=True, is_active=True)
                db.add(user); db.flush()
                session, _secret = create_session(db, user); db.commit()
                return user.id, {"Authorization": f"Bearer {create_access_token(user, session.id)}"}
        yield client, factory, account
    app.dependency_overrides.clear()
    limiter.reset()
    engine.dispose()


def test_inbox_pagination_ownership_unread_and_safe_relative_actions(notification_client):
    client, factory, account = notification_client
    first_id, first = account("First")
    second_id, second = account("Second")
    with factory() as db:
        create_notification(db, recipient_id=first_id, event_key="order:1", category="order",
            title="Order update", body="Your order status changed.", action_path="/orders/CR-1")
        create_notification(db, recipient_id=first_id, event_key="order:2", category="order",
            title="Order update two", body="A second status update.")
        db.commit()
    page = client.get("/api/v1/notifications?page=1&page_size=1", headers=first)
    assert page.status_code == 200
    assert page.json()["total"] == 2 and page.json()["unread_count"] == 2
    assert page.json()["pages"] == 2 and page.json()["items"][0]["action_path"] is None
    own_id = page.json()["items"][0]["id"]
    assert client.patch(f"/api/v1/notifications/{own_id}/read", headers=second).status_code == 404
    assert client.patch(f"/api/v1/notifications/{own_id}/read", headers=first).status_code == 200
    assert client.get("/api/v1/notifications?unread_only=true", headers=first).json()["total"] == 1
    assert client.post("/api/v1/notifications/read-all", headers=first).json()["updated"] == 1
    assert client.get("/api/v1/notifications", headers=second).json()["total"] == 0
    assert client.get("/api/v1/notifications?page_size=101", headers=first).status_code == 422


def test_event_idempotency_preferences_and_reject_unsafe_paths(notification_client):
    client, factory, account = notification_client
    user_id, headers = account("Prefs")
    defaults = client.get("/api/v1/notifications/preferences", headers=headers)
    assert defaults.status_code == 200
    assert defaults.json()["in_app_enabled"] is True and defaults.json()["email_enabled"] is True
    assert defaults.json()["category_settings"] == {}
    with factory() as db:
        assert db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id)) is None
    changed = client.put("/api/v1/notifications/preferences", headers=headers, json={
        "in_app_enabled": True, "email_enabled": True,
        "category_settings": {"order": {"in_app": False, "email": False}},
    })
    assert changed.status_code == 200
    with factory() as db:
        assert create_notification(db, recipient_id=user_id, event_key="order:disabled", category="order",
            title="Hidden", body="Preference suppresses this.", action_path=None,
            email_subject="Order", email_body="Hidden") is False
        assert create_notification(db, recipient_id=user_id, event_key="order:visible", category="account",
            title="Visible", body="Allowed by default.") is True
        assert create_notification(db, recipient_id=user_id, event_key="order:visible", category="account",
            title="Duplicate", body="Duplicate") is False
        with pytest.raises(ValueError):
            create_notification(db, recipient_id=user_id, event_key="bad:path", category="order",
                title="Bad", body="Bad", action_path="https://attacker.example")
        with pytest.raises(ValueError):
            create_notification(db, recipient_id=user_id, event_key="header:injection", category="account",
                title="Bad", body="Bad", email_subject="Good" + chr(13) + chr(10) + "Bcc: evil@example.com", email_body="Body")
        db.commit()
        assert db.scalar(select(Notification).where(Notification.event_key == "order:visible")) is not None
        assert db.scalar(select(EmailDelivery).where(EmailDelivery.event_key == "order:disabled")) is None
    assert changed.json()["category_settings"]["order"] == {"in_app": False, "email": False}
    assert client.put("/api/v1/notifications/preferences", headers=headers,
        json={"category_settings": {"arbitrary": {"email": True}}}).status_code == 422


def test_action_email_outbox_encrypts_one_use_link_and_is_idempotent(notification_client):
    client, factory, account = notification_client
    user_id, _headers = account("Action")
    with factory() as db:
        user = db.get(User, user_id)
        token="one-time-secret-token"
        db.add(AuthActionToken(user_id=user_id,purpose="verify_email",token_hash=sha256(token.encode()).hexdigest(),expires_at=datetime.now(timezone.utc)+timedelta(hours=1)))
        db.flush()
        assert enqueue_action_email(db, user, "verify_email", token, "https://crownd.example")
        assert not enqueue_action_email(db, user, "verify_email", "one-time-secret-token", "https://crownd.example")
        db.commit()
        row = db.scalar(select(EmailDelivery).where(EmailDelivery.recipient_id == user_id))
        assert "one-time-secret-token" not in row.encrypted_message
        rendered = decrypt_email(row.encrypted_message, user.email)
        assert "#token=one-time-secret-token" in rendered.text
        assert "one-time-secret-token" not in row.event_key


def test_worker_disabled_provider_suppresses_without_claiming_delivery(notification_client, monkeypatch):
    _client, factory, account = notification_client
    user_id, _headers = account("Disabled")
    monkeypatch.setattr(settings, "email_mode", "disabled")
    with factory() as db:
        create_notification(db, recipient_id=user_id, event_key="security:essential", category="security",
            title="Password changed", body="Security notice.", email_subject="Password changed",
            email_body="Password changed", essential_email=True)
        db.commit()
        assert process_due_deliveries(db, batch_size=1) == 1
        row = db.scalar(select(EmailDelivery))
        assert row.status == "suppressed" and row.last_error_code == "provider_disabled"
        assert row.attempt_count == 1 and row.delivered_at is None


def test_worker_retries_with_bounded_backoff_then_records_provider_acceptance(notification_client, monkeypatch):
    _client, factory, account = notification_client
    user_id, _headers = account("Retry")
    monkeypatch.setattr(settings, "email_mode", "smtp")
    calls = []
    class Provider:
        def send(self, message):
            calls.append(message)
            if len(calls) == 1:
                raise EmailDeliveryError("redacted")
            return True
    import app.services.notifications as service
    monkeypatch.setattr(service, "get_email_provider", lambda: Provider())
    with factory() as db:
        create_notification(db, recipient_id=user_id, event_key="security:retry", category="security",
            title="Account notice", body="Notice", email_subject="Subject", email_body="Safe text")
        db.commit()
        before = utcnow()
        assert process_due_deliveries(db, batch_size=1) == 1
        row = db.scalar(select(EmailDelivery))
        assert row.status == "pending" and row.attempt_count == 1
        assert row.last_error_code == "provider_error"
        assert row.next_attempt_at.replace(tzinfo=timezone.utc) >= before + timedelta(seconds=59)
        row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        assert process_due_deliveries(db, batch_size=1) == 1
        assert row.status == "sent" and row.attempt_count == 2 and row.delivered_at is not None
        assert calls[-1].to == "retry@example.test" and calls[-1].text == "Safe text"


def test_worker_stops_after_five_attempts(notification_client, monkeypatch):
    _client, factory, account = notification_client
    user_id, _headers = account("Failing")
    monkeypatch.setattr(settings, "email_mode", "smtp")
    class FailingProvider:
        def send(self, message):
            raise EmailDeliveryError("provider details must not persist")
    import app.services.notifications as service
    monkeypatch.setattr(service, "get_email_provider", lambda: FailingProvider())
    with factory() as db:
        create_notification(db, recipient_id=user_id, event_key="security:bounded", category="security",
            title="Notice", body="Notice", email_subject="Subject", email_body="Body")
        db.commit()
        for attempt in range(5):
            row = db.scalar(select(EmailDelivery))
            row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
            assert process_due_deliveries(db, batch_size=1) == 1
        row = db.scalar(select(EmailDelivery))
        assert row.status == "failed" and row.attempt_count == 5
        assert row.last_error_code == "provider_error"
        assert process_due_deliveries(db, batch_size=1) == 0


def test_admin_delivery_monitor_is_role_gated_and_never_exposes_payload(notification_client):
    client, factory, account = notification_client
    user_id, _user = account("Regular")
    _admin_id, admin = account("Admin", role="admin")
    with factory() as db:
        create_notification(db, recipient_id=user_id, event_key="account:1", category="account",
            title="Notice", body="Body", email_subject="Private subject", email_body="Private body")
        db.commit()
    assert client.get("/api/v1/admin/notification-deliveries", headers=_user).status_code == 403
    result = client.get("/api/v1/admin/notification-deliveries", headers=admin)
    assert result.status_code == 200 and result.json()["total"] == 1
    serialized = str(result.json())
    assert "Private subject" not in serialized and "Private body" not in serialized
    assert "encrypted_message" not in serialized and "recipient_id" not in serialized
    summary = client.get("/api/v1/admin/notification-deliveries/summary", headers=admin)
    assert summary.status_code == 200 and summary.json()["worker_status"] == "not_measured"


def test_registration_queues_encrypted_verification_and_worker_is_separate(notification_client):
    client, factory, _account = notification_client
    response = client.post("/api/v1/auth/register", json={"name": "Verify Person", "email": "verify@example.com",
        "password": "a-very-strong-password", "role": "customer"})
    assert response.status_code == 202 and response.json()["email_delivery_enabled"] is False
    with factory() as db:
        user = db.scalar(select(User).where(User.email == "verify@example.com"))
        action = db.scalar(select(AuthActionToken).where(AuthActionToken.user_id == user.id))
        delivery = db.scalar(select(EmailDelivery).where(EmailDelivery.recipient_id == user.id))
        assert action and delivery and delivery.essential and delivery.status == "pending"
        assert action.token_hash not in delivery.encrypted_message
        assert "verify@example.com" not in delivery.encrypted_message
        message = decrypt_email(delivery.encrypted_message, user.email)
        token = message.text.split("#token=", 1)[1].split("\n", 1)[0]
    assert client.post("/api/v1/auth/email/verification/confirm", json={"token": token}).status_code == 200
    with factory() as db:
        assert db.scalar(select(Notification).where(Notification.recipient_id == user.id,
            Notification.category == "account", Notification.title == "Email verified")) is not None
