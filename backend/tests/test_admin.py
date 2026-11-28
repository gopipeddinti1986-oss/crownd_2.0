from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api.v1.auth import limiter
from app.database import Base, get_db
from app.main import app
from app.models.entities import (AdminAuditEvent, AdminDispute, AdminDisputeEvent, AuthSession, BrandProfile, Campaign,
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


def test_admin_mutation_rate_limit_is_enforced(admin_client):
    client, _factory, account = admin_client
    admin_id, admin = account("admin", "Rate Limit Admin")
    target_id, _target = account("customer", "Rate Limit Target")
    responses=[client.post(f"/api/v1/admin/users/{target_id}/lifecycle",headers=admin,
        json={"active":False,"reason":"valid reason for test","confirmation":"WRONG"}) for _ in range(11)]
    assert all(response.status_code == 422 for response in responses[:10])
    assert responses[10].status_code == 429


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


def test_admin_product_moderation_is_paginated_audited_and_preserves_product_record(admin_client):
    client,factory,account=admin_client
    _,admin=account("admin","Product Moderator")
    brand_id,_=account("brand","Moderated Seller")
    with factory() as db:
        product=Product(brand_id=brand_id,name="Moderated Item",slug="moderated-item",price=Decimal("25.00"),stock=5,status="active")
        db.add(product);db.commit();product_id=product.id
    assert client.get("/api/v1/admin/products").status_code==401
    listed=client.get("/api/v1/admin/products",headers=admin,params={"q":"Moderated","page_size":1})
    assert listed.status_code==200 and listed.json()["total"]==1
    rejected=client.post(f"/api/v1/admin/products/{product_id}/moderation",headers=admin,json={"status":"inactive","reason":"Valid reason to suspend listing","confirmation":"WRONG"})
    assert rejected.status_code==422
    changed=client.post(f"/api/v1/admin/products/{product_id}/moderation",headers=admin,json={"status":"inactive","reason":"Valid reason to suspend listing","confirmation":"DEACTIVATE"})
    assert changed.status_code==200 and changed.json()["status"]=="inactive"
    with factory() as db:
        assert db.get(Product,product_id) is not None and db.get(Product,product_id).status=="inactive"
        event=db.query(AdminAuditEvent).filter_by(entity_type="product",entity_id=str(product_id)).one()
        assert event.reason=="Valid reason to suspend listing"
    assert client.post(f"/api/v1/admin/products/{product_id}/moderation",headers=admin,json={"status":"active","reason":"Restore reviewed product","confirmation":"ACTIVATE"}).status_code==200


def test_customer_can_report_owned_order_and_admin_resolution_preserves_financial_state(admin_client):
    client,factory,account=admin_client
    _,admin=account("admin","Dispute Administrator")
    customer_id,customer=account("customer","Dispute Customer")
    _,other_customer=account("customer","Other Dispute Customer")
    brand_id,_=account("brand","Dispute Seller")
    with factory() as db:
        product=Product(brand_id=brand_id,name="Dispute Product",slug="dispute-product",price=Decimal("80.00"),stock=2,status="active")
        db.add(product);db.flush()
        order=Order(public_id="ORDER-DISPUTE-1",customer_name="Dispute Customer",customer_email="disputecustomer@example.test",customer_id=customer_id,product_id=product.id,quantity=1,amount=Decimal("80.00"),payment_method="cod",payment_status="unpaid",status="delivered")
        db.add(order);db.commit();order_id=order.id
    denied=client.post("/api/v1/disputes",headers=other_customer,json={"order_id":"ORDER-DISPUTE-1","summary":"Order issue reported","reason":"I am not the customer for this order"})
    assert denied.status_code==404
    created=client.post("/api/v1/disputes",headers=customer,json={"order_id":"ORDER-DISPUTE-1","summary":"Package condition concern","reason":"The delivered package arrived with a damaged seal"})
    assert created.status_code==201 and created.json()["financial_history_mutated"] is False
    admin_inbox=client.get("/api/v1/notifications",headers=admin)
    assert any(item["title"]=="A customer dispute was opened" for item in admin_inbox.json()["items"])
    assert client.post("/api/v1/disputes",headers=customer,json={"order_id":"ORDER-DISPUTE-1","summary":"Another order concern","reason":"A duplicate open issue should be rejected"}).status_code==409
    own_cases=client.get("/api/v1/disputes",headers=customer)
    assert own_cases.status_code==200 and own_cases.json()["total"]==1
    assert client.get("/api/v1/disputes",headers=other_customer).json()["total"]==0
    case_id=created.json()["id"]
    changed=client.post(f"/api/v1/admin/disputes/{case_id}/status",headers=admin,json={"status":"under_review","reason":"Reviewing order evidence with support","confirmation":"UNDER_REVIEW"})
    assert changed.status_code==200
    assert client.post(f"/api/v1/admin/disputes/{case_id}/status",headers=admin,json={"status":"resolved","reason":"Evidence review is now completed","confirmation":"RESOLVED"}).status_code==200
    inbox=client.get("/api/v1/notifications",headers=customer)
    assert inbox.status_code==200 and any(item["title"]=="Order issue status updated" for item in inbox.json()["items"])
    with factory() as db:
        order=db.get(Order,order_id)
        case=db.get(AdminDispute,case_id)
        assert order.amount==Decimal("80.00") and order.payment_status=="unpaid" and order.status=="delivered"
        assert case.status=="resolved" and db.query(AdminDisputeEvent).filter_by(dispute_id=case_id).count()==3


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
