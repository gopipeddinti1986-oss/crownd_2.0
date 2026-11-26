from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api.v1.auth import limiter
from app.database import Base, get_db
from app.main import app
from app.models.entities import (AdminAuditEvent, AdminDisputeEvent, AuthSession, BrandProfile, Campaign,
    CreatorProfile, LedgerEntry, Order, Product, ReferralRiskFlag, User)
from app.security import create_access_token, hash_password
from app.services.auth import create_session


@pytest.fixture
def admin_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    def override_db():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    limiter.reset()
    with TestClient(app) as client:
        def account(role, name):
            with factory() as db:
                user = User(name=name, email=f"{name.lower().replace(' ','.')}@example.test", role=role,
                    password_hash=hash_password("admin-test-password"), email_verified=True)
                db.add(user); db.flush()
                if role == "creator": db.add(CreatorProfile(user_id=user.id, username=f"user{user.id}"))
                if role == "brand": db.add(BrandProfile(user_id=user.id, name=name))
                session, _secret = create_session(db, user); db.commit()
                return user.id, {"Authorization": f"Bearer {create_access_token(user, session.id)}"}
        yield client, factory, account
    app.dependency_overrides.clear(); limiter.reset(); engine.dispose()


def test_admin_user_lifecycle_requires_reason_revokes_sessions_and_masks_pii(admin_client):
    client, factory, account = admin_client
    admin_id, admin = account("admin", "Admin Person")
    target_id, target = account("creator", "Creator Person")
    assert client.get("/api/v1/admin/users", headers=target).status_code == 403
    listing = client.get("/api/v1/admin/users?q=Creator", headers=admin)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["email_masked"].endswith("@example.test")
    assert "email" not in listing.json()["items"][0]
    bad = client.post(f"/api/v1/admin/users/{target_id}/lifecycle", headers=admin,
        json={"active": False, "reason": "Bad", "confirmation": "SUSPEND"})
    assert bad.status_code == 422
    changed = client.post(f"/api/v1/admin/users/{target_id}/lifecycle", headers=admin,
        json={"active": False, "reason": "Temporary restriction pending review", "confirmation": "SUSPEND"})
    assert changed.status_code == 200 and changed.json()["sessions_revoked"] is True
    assert client.get("/api/v1/auth/me", headers=target).status_code == 401
    with factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == target_id))
        event = db.scalar(select(AdminAuditEvent).where(AdminAuditEvent.entity_id == str(target_id)))
        assert session.revoked_at is not None and event.reason == "Temporary restriction pending review"
    self_suspend = client.post(f"/api/v1/admin/users/{admin_id}/lifecycle", headers=admin,
        json={"active": False, "reason": "Trying to suspend self", "confirmation": "SUSPEND"})
    assert self_suspend.status_code == 409
    role_escalation = client.post(f"/api/v1/admin/users/{target_id}/lifecycle", headers=admin,
        json={"active": True, "role": "admin", "reason": "Attempt to elevate account", "confirmation": "REACTIVATE"})
    assert role_escalation.status_code == 422


def test_manual_verification_campaign_moderation_and_risk_review_are_audited(admin_client):
    client, factory, account = admin_client
    admin_id, admin = account("admin", "Admin Person")
    creator_id, _creator = account("creator", "Creator Person")
    brand_id, _brand = account("brand", "Brand Person")
    with factory() as db:
        campaign = Campaign(brand_id=brand_id, title="Review me", slug="review-me", status="draft")
        flag = ReferralRiskFlag(risk_code="REPEATED_CUSTOMER_PATTERN", details="Repeated pattern; human review only.")
        db.add_all([campaign, flag]); db.commit(); campaign_id=campaign.id; flag_id=flag.id
    verification = client.post(f"/api/v1/admin/verification/creator/{creator_id}", headers=admin,
        json={"status":"verified","reason":"Profile details reviewed manually", "confirmation":"VERIFIED"})
    assert verification.status_code == 200 and verification.json()["method"] == "manual_review"
    publish = client.post(f"/api/v1/admin/campaigns/{campaign_id}/moderation", headers=admin,
        json={"status":"published","reason":"Campaign brief reviewed by staff", "confirmation":"PUBLISHED"})
    assert publish.status_code == 200
    review = client.patch(f"/api/v1/admin/referral-risk/{flag_id}", headers=admin,
        json={"status":"dismissed","reason":"Signal reviewed; no policy breach found"})
    assert review.status_code == 200
    with factory() as db:
        assert db.get(CreatorProfile, creator_id) is None # user id is not profile primary key
        profile = db.scalar(select(CreatorProfile).where(CreatorProfile.user_id == creator_id))
        assert profile.verification == "verified"
        assert db.get(Campaign, campaign_id).status == "published"
        assert db.get(ReferralRiskFlag, flag_id).status == "dismissed"
        events = db.scalars(select(AdminAuditEvent).order_by(AdminAuditEvent.id)).all()
        assert len(events) == 3 and all(row.reason for row in events)


def test_disputes_preserve_ledger_and_admin_history_is_append_only(admin_client):
    client, factory, account = admin_client
    admin_id, admin = account("admin", "Admin Person")
    brand_id, _brand = account("brand", "Brand Person")
    creator_id, _creator = account("creator", "Creator Person")
    with factory() as db:
        product = Product(brand_id=brand_id, name="Test", slug="test-product", price=Decimal("20.00"), stock=5)
        db.add(product); db.flush()
        order = Order(public_id="ORD-ADMIN-1", customer_name="Customer", customer_email="customer@example.test",
            product_id=product.id, quantity=1, amount=Decimal("20.00"))
        db.add(order); db.flush()
        ledger = LedgerEntry(reference="ORD-ADMIN-1", user_id=creator_id, entry_type="reward_credit", amount=Decimal("2.00"))
        db.add(ledger); db.commit(); order_id=order.id; ledger_id=ledger.id
    denied = client.post("/api/v1/admin/disputes", headers={"Authorization": "Bearer invalid"},
        json={"order_id": order_id, "summary":"Review order record", "reason":"Investigate a reported issue"})
    assert denied.status_code == 401
    opened = client.post("/api/v1/admin/disputes", headers=admin,
        json={"order_id": order_id, "summary":"Review reported order concern", "reason":"Customer raised a delivery concern"})
    assert opened.status_code == 201 and opened.json()["financial_history_mutated"] is False
    case_id = opened.json()["id"]
    resolved = client.post(f"/api/v1/admin/disputes/{case_id}/status", headers=admin,
        json={"status":"resolved","reason":"Evidence reviewed; case closed without ledger adjustment", "confirmation":"RESOLVED"})
    assert resolved.status_code == 200
    with factory() as db:
        assert db.get(LedgerEntry, ledger_id).amount == Decimal("2.00")
        assert len(db.scalars(select(AdminDisputeEvent).where(AdminDisputeEvent.dispute_id == case_id)).all()) == 2
        event = db.scalar(select(AdminAuditEvent).where(AdminAuditEvent.action == "dispute.opened"))
        with pytest.raises(ValueError, match="append-only"):
            event.reason = "tampered"
            db.flush()
        db.rollback()
