from datetime import datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api.v1.auth import limiter
from app.database import Base, get_db
from app.main import app
from app.models.entities import Application, BrandProfile, Campaign, CampaignProduct, Cart, CartItem, Click, Conversion, ConversionEvent, Order, OrderItem, PaymentAttempt, Product, Referral, ReferralActivity, ReferralRiskFlag, Reward, RewardRule, LedgerEntry, User, VisitorAttribution
from app.core.config import settings
from app.security import create_access_token, hash_password
from app.services.auth import create_session


@pytest.fixture
def commerce_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def commerce_client(commerce_db):
    def override_db():
        db = commerce_db()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    limiter.reset()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    limiter.reset()


def create_account(factory, name, email, role):
    with factory() as db:
        user = User(name=name, email=email, role=role, password_hash=hash_password("commerce-testing-password"), email_verified=True)
        db.add(user)
        db.flush()
        if role == "brand":
            db.add(BrandProfile(user_id=user.id, name=name, industry="Wellness", website="https://brand.example"))
        db.commit()
        db.refresh(user)
        session, _cookie = create_session(db, user)
        db.commit()
        token = create_access_token(user, session.id)
        return user.id, {"Authorization": f"Bearer {token}"}


def create_product(factory, brand_id, **overrides):
    values = {"brand_id": brand_id, "name": "Cedar Serum", "slug": f"cedar-serum-{brand_id}-{overrides.get('stock', 8)}", "description": "Botanical daily care", "category": "Beauty", "price": Decimal("100.00"), "sale_price": Decimal("80.00"), "stock": 8, "image_url": "https://img.example/serum.jpg", "image_urls": ["https://img.example/serum.jpg", "https://img.example/back.jpg"], "specifications": {"size": "30 ml"}, "status": "active"}
    values.update(overrides)
    with factory() as db:
        product = Product(**values)
        db.add(product)
        db.commit()
        db.refresh(product)
        return product.id


def address():
    return {"shipping_address": {"name": "Customer Person", "phone": "+91 98765 43210", "line1": "12 Market Road", "line2": "Floor 2", "city": "Rajamahendravaram", "state": "Andhra Pradesh", "postal_code": "533101", "country": "IN"}}


def add_to_cart(client, headers, product_id, quantity=1):
    return client.post("/api/v1/cart/items", headers=headers, json={"product_id": product_id, "quantity": quantity})


def test_discovery_search_filters_sort_pagination_and_details(commerce_db, commerce_client):
    brand, _ = create_account(commerce_db, "Noya Botanics", "brand1@example.com", "brand")
    other_brand, _ = create_account(commerce_db, "Morrow Pantry", "brand2@example.com", "brand")
    first = create_product(commerce_db, brand, stock=8)
    create_product(commerce_db, other_brand, name="Oat Balm", slug="oat-balm", category="Body", price=Decimal("55.00"), sale_price=None, stock=0, image_urls=[], specifications={})
    res = commerce_client.get("/api/v1/products", params={"q": "cedar", "category": "Beauty", "brand_id": brand, "min_price": "70", "max_price": "90", "in_stock": "true", "page": 1, "page_size": 1})
    assert res.status_code == 200 and res.json()["total"] == 1
    assert res.json()["items"][0]["id"] == first
    assert res.json()["items"][0]["effective_price"] == "80.00"
    assert res.json()["items"][0]["discount_percent"] == 20
    assert commerce_client.get("/api/v1/products", params={"q": "Noya"}).json()["total"] == 1
    assert commerce_client.get("/api/v1/products/categories").json() == ["Beauty", "Body"]
    detail = commerce_client.get(f"/api/v1/products/{first}")
    assert detail.status_code == 200 and detail.json()["specifications"] == {"size": "30 ml"}
    assert detail.json()["brand"]["name"] == "Noya Botanics"
    assert commerce_client.get("/api/v1/products", params={"q": "no-such-product"}).json()["items"] == []


def test_authenticated_cart_persists_recalculates_and_enforces_ownership(commerce_db, commerce_client):
    brand, _ = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    _customer, customer_headers = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    _other, other_headers = create_account(commerce_db, "Other", "other@example.com", "customer")
    product_id = create_product(commerce_db, brand)
    added = add_to_cart(commerce_client, customer_headers, product_id, 2)
    assert added.status_code == 201 and added.json()["subtotal"] == "160.00"
    item_id = added.json()["items"][0]["id"]
    assert commerce_client.get("/api/v1/cart", headers=customer_headers).json()["item_count"] == 2
    updated = commerce_client.patch(f"/api/v1/cart/items/{item_id}", headers=customer_headers, json={"quantity": 3})
    assert updated.status_code == 200 and updated.json()["subtotal"] == "240.00"
    assert commerce_client.patch(f"/api/v1/cart/items/{item_id}", headers=other_headers, json={"quantity": 1}).status_code == 404
    assert commerce_client.post("/api/v1/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1, "price": 0.01}).status_code == 422
    cleared = commerce_client.delete("/api/v1/cart", headers=customer_headers)
    assert cleared.status_code == 204 and commerce_client.get("/api/v1/cart", headers=customer_headers).json()["items"] == []


def test_checkout_trusts_database_prices_is_idempotent_and_records_order_items(commerce_db, commerce_client):
    brand, brand_headers = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    customer_id, customer_headers = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    product_id = create_product(commerce_db, brand, stock=5)
    assert add_to_cart(commerce_client, customer_headers, product_id, 2).status_code == 201
    key = "order-retry-key-0001"
    first = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": key}, json={**address(), "price": 0.01, "amount": 0.01})
    assert first.status_code == 422  # Checkout schema rejects client-supplied totals.
    first = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": key}, json={**address(), "payment_method": "cod"})
    assert first.status_code == 201, first.text
    order = first.json()
    assert order["amount"] == "160.00" and order["payment_method"] == "cod" and order["payment_status"] == "unpaid" and order["status"] == "confirmed"
    assert order["items"][0]["unit_price"] == "80.00" and order["items"][0]["quantity"] == 2
    replay = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": key}, json={**address(), "payment_method": "cod"})
    assert replay.status_code == 200 and replay.json()["id"] == order["id"]
    with commerce_db() as db:
        product = db.get(Product, product_id)
        assert product.stock == 3
        saved = db.scalar(select(Order).where(Order.idempotency_key == key))
        assert saved and saved.customer_id == customer_id
        assert len(db.scalars(select(OrderItem).where(OrderItem.order_id == saved.id)).all()) == 1
    history = commerce_client.get("/api/v1/orders", headers=customer_headers).json()
    assert history["total"] == 1 and history["items"][0]["id"] == order["id"]
    detail = commerce_client.get(f"/api/v1/orders/{order['id']}", headers=customer_headers)
    assert detail.status_code == 200 and detail.json()["shipping_address"]["postal_code"] == "533101"
    # Existing brand order reporting keeps its legacy list shape; storefront asks for its own paginated customer view.
    business_view = commerce_client.get("/api/v1/orders", headers=brand_headers)
    assert isinstance(business_view.json(), list) and business_view.json()[0]["id"] == order["id"]


def test_inventory_race_guard_unavailable_cart_and_cancel_restores_stock(commerce_db, commerce_client):
    brand, brand_headers = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    customer_id, customer_headers = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    other_id, other_headers = create_account(commerce_db, "Other", "other@example.com", "customer")
    product_id = create_product(commerce_db, brand, stock=2, sale_price=None)
    assert add_to_cart(commerce_client, customer_headers, product_id, 2).status_code == 201
    assert add_to_cart(commerce_client, other_headers, product_id, 1).status_code == 201
    first = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "inventory-order-0001"}, json={**address(), "payment_method": "cod"})
    assert first.status_code == 201
    second = commerce_client.post("/api/v1/checkout", headers={**other_headers, "Idempotency-Key": "inventory-order-0002"}, json={**address(), "payment_method": "cod"})
    assert second.status_code == 409
    assert commerce_client.get("/api/v1/cart", headers=other_headers).json()["unavailable_count"] == 1
    assert commerce_client.get(f"/api/v1/orders/{first.json()['id']}", headers=other_headers).status_code == 404
    assert commerce_client.post(f"/api/v1/orders/{first.json()['id']}/cancel", headers=other_headers).status_code == 404
    cancelled = commerce_client.post(f"/api/v1/orders/{first.json()['id']}/cancel", headers=customer_headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert commerce_client.get("/api/v1/products", params={"brand_id": brand}).json()["items"][0]["stock"] == 2
    assert commerce_client.post(f"/api/v1/orders/{first.json()['id']}/cancel", headers=customer_headers).status_code == 409
    assert commerce_client.patch(f"/api/v1/orders/{first.json()['id']}/status", headers=brand_headers, json={"status": "processing"}).status_code == 403


def test_referral_cookie_attribution_is_signed_and_validated_at_checkout(commerce_db, commerce_client):
    brand, _ = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    customer_id, customer_headers = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    creator_id, creator_headers = create_account(commerce_db, "Jules Lane", "creator@example.com", "creator")
    product_id = create_product(commerce_db, brand)
    with commerce_db() as db:
        campaign = Campaign(brand_id=brand, product_id=product_id, title="Ritual", slug="ritual", description="", category="Beauty", platforms="Instagram", reward_model="percentage", reward_rate=Decimal("10"), budget=Decimal("1000"), status="published")
        db.add(campaign)
        db.flush()
        db.add(Application(campaign_id=campaign.id, creator_id=creator_id, status="accepted"))
        referral = Referral(campaign_id=campaign.id, creator_id=creator_id, code="JULES10", active=True)
        db.add(referral)
        db.commit()
    tracked = commerce_client.get("/api/v1/r/JULES10")
    assert tracked.status_code == 200 and "crownd_referral=" in tracked.headers["set-cookie"]
    assert tracked.json()["destination"] == f"/products/{product_id}"
    assert add_to_cart(commerce_client, customer_headers, product_id).status_code == 201
    created = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "referral-order-0001"}, json={**address(), "payment_method": "demo"})
    assert created.status_code == 201 and created.json()["referral"]["creator_name"] == "Jules Lane"
    with commerce_db() as db:
        order = db.scalar(select(Order).where(Order.customer_id == customer_id))
        assert order.referral_id is not None and order.payment_method == "demo"
        demo_reward = db.scalar(select(Reward).where(Reward.order_id == order.id))
        assert demo_reward and demo_reward.is_demo is True
        demo_reward.status = "eligible"
        db.commit()
    assert commerce_client.post("/api/v1/payouts", headers=creator_headers).status_code == 410
    # Tampering with the attribution cookie cannot assign an arbitrary referral.
    commerce_client.cookies.set("crownd_referral", "1.9999999999.forged")
    commerce_client.cookies.set("crownd_attribution", "forged.visitor.signature")
    assert add_to_cart(commerce_client, customer_headers, product_id).status_code == 201
    uncredited = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "tampered-referral-001"}, json={**address(), "payment_method": "cod"})
    assert uncredited.status_code == 201 and uncredited.json()["referral"] is None


def test_product_creation_validates_sale_price_and_inventory(commerce_db, commerce_client):
    _brand_id, brand_headers = create_account(commerce_db, "Noya", "seller@example.com", "brand")
    invalid_sale = commerce_client.post("/api/v1/products", headers=brand_headers, json={"name": "Discounted Oil", "price": "100.00", "sale_price": "100.00", "stock": 2})
    assert invalid_sale.status_code == 422
    invalid_stock = commerce_client.post("/api/v1/products", headers=brand_headers, json={"name": "Negative Stock", "price": "100.00", "stock": -1})
    assert invalid_stock.status_code == 422


def test_checkout_cors_preflight_allows_idempotency_key(commerce_client):
    response = commerce_client.options("/api/v1/checkout", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,idempotency-key"})
    assert response.status_code == 200
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()


def test_product_stock_bounds_and_order_lifecycle_owner(commerce_db, commerce_client):
    brand, brand_headers = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    _customer_id, customer_headers = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    _admin_id, admin_headers = create_account(commerce_db, "Admin", "admin@example.com", "admin")
    product_id = create_product(commerce_db, brand, stock=1, sale_price=None)
    assert add_to_cart(commerce_client, customer_headers, product_id, 2).status_code == 409
    assert add_to_cart(commerce_client, customer_headers, product_id).status_code == 201
    order = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "lifecycle-order-0001"}, json={**address(), "payment_method": "cod"}).json()
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=brand_headers, json={"status": "processing"}).status_code == 403
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=admin_headers, json={"status": "processing"}).status_code == 200
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=admin_headers, json={"status": "processing"}).status_code == 409
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=admin_headers, json={"status": "shipped"}).status_code == 200
    delivered = commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=admin_headers, json={"status": "delivered"})
    assert delivered.status_code == 200 and delivered.json()["payment_status"] == "unpaid"
    assert commerce_client.post(f"/api/v1/orders/{order['id']}/cancel", headers=customer_headers).status_code == 409


def test_demo_payment_is_backend_simulated_idempotent_and_identified(commerce_db, commerce_client):
    brand, _ = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    _customer_id, customer = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    product_id = create_product(commerce_db, brand, stock=4)
    assert add_to_cart(commerce_client, customer, product_id, 2).status_code == 201
    headers = {**customer, "Idempotency-Key": "demo-paid-checkout-001"}
    placed = commerce_client.post("/api/v1/checkout", headers=headers, json={**address(), "payment_method": "demo"})
    assert placed.status_code == 201
    result = placed.json()
    assert result["payment_method"] == "demo" and result["payment_status"] == "paid" and result["status"] == "confirmed"
    assert result["transaction_reference"].startswith("DEMO-")
    assert "no real payment" in result["payment_notes"].lower()
    assert result["payment_attempts"][0]["status"] == "paid"
    replay = commerce_client.post("/api/v1/checkout", headers=headers, json={**address(), "payment_method": "demo"})
    assert replay.status_code == 200 and replay.json()["id"] == result["id"]
    with commerce_db() as db:
        assert db.get(Product, product_id).stock == 2
        assert len(db.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == db.scalar(select(Order.id).where(Order.public_id == result["id"])))).all()) == 1


def test_demo_payment_failure_cancels_order_and_restores_inventory(commerce_db, commerce_client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    brand, _ = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    _customer_id, customer = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    product_id = create_product(commerce_db, brand, stock=3)
    assert add_to_cart(commerce_client, customer, product_id, 2).status_code == 201
    headers = {**customer, "Idempotency-Key": "demo-failed-checkout-001", "X-Demo-Payment-Test-Failure": "true"}
    failed = commerce_client.post("/api/v1/checkout", headers=headers, json={**address(), "payment_method": "demo"})
    assert failed.status_code == 201
    assert failed.json()["payment_method"] == "demo" and failed.json()["payment_status"] == "failed" and failed.json()["status"] == "cancelled"
    assert failed.json()["transaction_reference"].startswith("DEMO-")
    assert commerce_client.get("/api/v1/products", params={"brand_id": brand}).json()["items"][0]["stock"] == 3
    replay = commerce_client.post("/api/v1/checkout", headers=headers, json={**address(), "payment_method": "demo"})
    assert replay.status_code == 200 and replay.json()["payment_status"] == "failed"
    with commerce_db() as db:
        order = db.scalar(select(Order).where(Order.public_id == failed.json()["id"]))
        assert len(db.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id)).all()) == 1


def test_cod_stays_unpaid_through_delivery_and_admin_collection_is_audited(commerce_db, commerce_client):
    brand, brand_headers = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    _customer_id, customer = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    _admin_id, admin = create_account(commerce_db, "Admin", "admin@example.com", "admin")
    product_id = create_product(commerce_db, brand, stock=2)
    assert add_to_cart(commerce_client, customer, product_id).status_code == 201
    order = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "cod-checkout-00001"}, json={**address(), "payment_method": "cod"}).json()
    assert order["payment_method"] == "cod" and order["payment_status"] == "unpaid" and order["status"] == "confirmed"
    assert order["transaction_reference"] is None
    assert commerce_client.post(f"/api/v1/admin/orders/{order['id']}/collect-payment", headers=customer).status_code == 403
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=brand_headers, json={"status": "processing"}).status_code == 403
    for status in ("processing", "shipped", "delivered"):
        response = commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=admin, json={"status": status})
        assert response.status_code == 200, response.text
        assert response.json()["payment_status"] == "unpaid"
    collected = commerce_client.post(f"/api/v1/admin/orders/{order['id']}/collect-payment", headers=admin)
    assert collected.status_code == 200
    payload = collected.json()
    assert payload["payment_status"] == "paid" and payload["payment_method"] == "cod"
    assert payload["transaction_reference"].startswith("COD-COLLECT-")
    assert payload["payment_confirmed_by"]["role"] == "admin" and payload["payment_confirmed_at"]
    assert commerce_client.post(f"/api/v1/admin/orders/{order['id']}/collect-payment", headers=admin).status_code == 409
    with commerce_db() as db:
        stored = db.scalar(select(Order).where(Order.public_id == order["id"]))
        attempt = db.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == stored.id))
        assert attempt.status == "paid" and attempt.confirmed_by is not None


def test_online_payment_is_disabled_and_admin_order_filters_are_protected(commerce_db, commerce_client):
    brand, _ = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    _customer_id, customer = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    _admin_id, admin = create_account(commerce_db, "Admin", "admin@example.com", "admin")
    product_id = create_product(commerce_db, brand)
    assert add_to_cart(commerce_client, customer, product_id).status_code == 201
    rejected = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "online-disabled-001"}, json={**address(), "payment_method": "online"})
    assert rejected.status_code == 409 and "coming soon" in rejected.json()["detail"]
    assert commerce_client.get("/api/v1/admin/orders", headers=customer).status_code == 403
    order = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "cod-admin-list-001"}, json={**address(), "payment_method": "cod"}).json()
    listing = commerce_client.get("/api/v1/admin/orders", headers=admin, params={"payment_method": "cod", "payment_status": "unpaid", "status": "confirmed", "q": order["id"]})
    assert listing.status_code == 200 and listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == order["id"]
    detail = commerce_client.get(f"/api/v1/admin/orders/{order['id']}", headers=admin)
    assert detail.status_code == 200 and detail.json()["payment_attempts"][0]["payment_method"] == "cod"


def test_customer_cannot_submit_payment_status_or_access_another_order(commerce_db, commerce_client):
    brand, _ = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    _customer_id, customer = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    _other_id, other = create_account(commerce_db, "Other", "other@example.com", "customer")
    product_id = create_product(commerce_db, brand)
    assert add_to_cart(commerce_client, customer, product_id).status_code == 201
    malicious = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "payment-tamper-0001"}, json={**address(), "payment_method": "cod", "payment_status": "paid", "amount": "0.01"})
    assert malicious.status_code == 422
    assert add_to_cart(commerce_client, customer, product_id).status_code == 201
    order = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "owner-safe-order-001"}, json={**address(), "payment_method": "cod"}).json()
    assert commerce_client.get(f"/api/v1/orders/{order['id']}", headers=other).status_code == 404
    assert commerce_client.post(f"/api/v1/admin/orders/{order['id']}/collect-payment", headers=other).status_code == 403


def test_cod_referral_reward_is_created_only_after_admin_collection(commerce_db, commerce_client):
    brand, _ = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    _customer_id, customer = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    creator_id, creator = create_account(commerce_db, "Creator", "creator@example.com", "creator")
    _admin_id, admin = create_account(commerce_db, "Admin", "admin@example.com", "admin")
    product_id = create_product(commerce_db, brand, sale_price=None, stock=3)
    with commerce_db() as db:
        campaign = Campaign(brand_id=brand, product_id=product_id, title="COD Campaign", slug="cod-campaign", description="", category="Beauty", platforms="Instagram", reward_model="percentage", reward_rate=Decimal("10"), budget=Decimal("500"), status="published")
        db.add(campaign)
        db.flush()
        db.add(Application(campaign_id=campaign.id, creator_id=creator_id, status="accepted"))
        referral = Referral(campaign_id=campaign.id, creator_id=creator_id, code="CODCREATOR", active=True)
        db.add(referral)
        db.commit()
    assert commerce_client.get("/api/v1/r/CODCREATOR").status_code == 200
    assert add_to_cart(commerce_client, customer, product_id).status_code == 201
    order = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "cod-referral-order-001"}, json={**address(), "payment_method": "cod"}).json()
    with commerce_db() as db:
        order_row = db.scalar(select(Order).where(Order.public_id == order["id"]))
        assert db.scalar(select(Reward).where(Reward.order_id == order_row.id)) is None
        assert db.scalar(select(LedgerEntry.id).where(LedgerEntry.order_id == order_row.id)) is None
    for status in ("processing", "shipped", "delivered"):
        assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=admin, json={"status": status}).status_code == 200
    assert commerce_client.post(f"/api/v1/admin/orders/{order['id']}/collect-payment", headers=admin).status_code == 200
    with commerce_db() as db:
        stored = db.scalar(select(Order).where(Order.public_id == order["id"]))
        reward = db.scalar(select(Reward).where(Reward.order_id == stored.id))
        assert reward and reward.creator_id == creator_id and reward.is_demo is False and reward.status == "pending"
    creator_rewards = commerce_client.get("/api/v1/rewards/me", headers=creator).json()
    assert len(creator_rewards) == 1 and creator_rewards[0]["is_demo"] is False and creator_rewards[0]["payable"] is False
    reward_id = creator_rewards[0]["id"]
    with commerce_db() as db:
        reward = db.get(Reward, reward_id)
        reward.eligible_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()
    assert commerce_client.post(f"/api/v1/admin/rewards/{reward_id}/approve", headers=admin, json={}).status_code == 200
    payout = commerce_client.post(f"/api/v1/admin/rewards/{reward_id}/simulated-payout", headers=admin, json={"reason": "admin simulation"})
    assert payout.status_code == 200 and payout.json()["actual_money_transferred"] is False
    assert "no actual money was transferred" in payout.json()["disclosure"].lower()
    assert commerce_client.post(f"/api/v1/admin/rewards/{reward_id}/simulated-payout", headers=admin, json={}).status_code == 409
    reversed_reward = commerce_client.post(f"/api/v1/admin/rewards/{reward_id}/reverse", headers=admin, json={"reason": "test reversal"})
    assert reversed_reward.status_code == 200 and reversed_reward.json()["status"] == "reversed"
    with commerce_db() as db:
        entries = db.scalars(select(LedgerEntry).where(LedgerEntry.reward_id == reward_id).order_by(LedgerEntry.id)).all()
        assert [(entry.direction,entry.entry_type) for entry in entries] == [("credit","REWARD_PENDING"),("memo","SIMULATED_PAYOUT_RECORDED"),("debit","REWARD_REVERSED")]
        with pytest.raises(ValueError,match="immutable"):
            db.delete(entries[0])
            db.flush()
        db.rollback()
        with commerce_db() as retry:
            entry=retry.get(LedgerEntry,entries[0].id)
            with pytest.raises(ValueError,match="immutable"):
                entry.description="tampered"
                retry.flush()


def test_phase5_reward_rule_precedence_demo_disclosure_and_role_scoped_apis(commerce_db, commerce_client):
    brand_id, brand = create_account(commerce_db, "Reward Brand", "phase5-brand@example.com", "brand")
    creator_id, creator = create_account(commerce_db, "Reward Creator", "phase5-creator@example.com", "creator")
    customer_id, customer = create_account(commerce_db, "Reward Customer", "phase5-customer@example.com", "customer")
    _admin_id, admin = create_account(commerce_db, "Reward Admin", "phase5-admin@example.com", "admin")
    product_id = create_product(commerce_db, brand_id, sale_price=None)
    with commerce_db() as db:
        campaign = Campaign(brand_id=brand_id, product_id=product_id, title="Rule precedence", slug="rule-precedence", description="", category="Beauty", platforms="Instagram", reward_model="percentage", reward_rate=Decimal("10"), budget=Decimal("500"), status="published")
        db.add(campaign)
        db.flush()
        db.add(Application(campaign_id=campaign.id, creator_id=creator_id, status="accepted"))
        db.add(Referral(campaign_id=campaign.id, creator_id=creator_id, code="PHASE5RULE", active=True))
        db.commit()
        campaign_id = campaign.id
    created = commerce_client.post("/api/v1/admin/reward-rules", headers=admin, json={"campaign_id": campaign_id, "product_id": product_id, "reward_type": "percentage", "rate": "12.500", "max_reward": "25.00"})
    assert created.status_code == 201, created.text
    assert created.json()["scope_key"] == f"campaign:{campaign_id}:product:{product_id}"
    assert commerce_client.get("/api/v1/admin/reward-rules", headers=brand).status_code == 403
    assert commerce_client.get("/api/v1/admin/rewards", headers=creator).status_code == 403
    assert commerce_client.post("/api/v1/payouts", headers=creator).status_code == 410
    assert commerce_client.get("/api/v1/r/PHASE5RULE").status_code == 200
    assert add_to_cart(commerce_client, customer, product_id).status_code == 201
    order_response = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "phase5-rule-demo"}, json={**address(), "payment_method": "demo"})
    assert order_response.status_code == 201
    with commerce_db() as db:
        order = db.scalar(select(Order).where(Order.customer_id == customer_id))
        reward = db.scalar(select(Reward).where(Reward.order_id == order.id))
        assert reward and reward.amount == Decimal("12.50")
        assert reward.status == "simulated" and reward.is_demo is True
        assert reward.calculation_snapshot["rule_source"] == "product_rule"
        assert reward.calculation_snapshot["eligible_amount"] == "100.00"
        assert reward.calculation_snapshot["rounding"] == "ROUND_HALF_UP"
        reward_id=reward.id
        ledger = db.scalars(select(LedgerEntry).where(LedgerEntry.reward_id == reward.id)).all()
        assert len(ledger) == 1 and ledger[0].direction == "memo" and ledger[0].idempotency_key
    updated_rule=commerce_client.put(f"/api/v1/admin/reward-rules/{created.json()['id']}",headers=admin,json={"rate":"20.000"})
    assert updated_rule.status_code==200 and updated_rule.json()["rate"]=="20.000"
    with commerce_db() as db:
        saved_reward=db.get(Reward,reward_id)
        assert saved_reward.amount==Decimal("12.50") and saved_reward.calculation_snapshot["rate"]=="12.500"
        db.add(ReferralRiskFlag(risk_code="TEST_PRIVACY",referral_id=saved_reward.referral_id,conversion_id=saved_reward.conversion_id,details="Customer email: private@example.test",status="open"))
        db.commit()
    listing = commerce_client.get("/api/v1/creator/rewards", headers=creator)
    assert listing.status_code == 200 and listing.json()["total"] == 1
    assert listing.json()["items"][0]["payable"] is False
    assert listing.json()["items"][0]["payout_disclosure"].startswith("CROWND does not transfer money")
    assert "customer_email" not in str(listing.json()) and "shipping_address" not in str(listing.json())
    creator_detail=commerce_client.get(f"/api/v1/creator/rewards/{reward_id}",headers=creator).json()
    assert creator_detail["risk_flags"][0]["details"] is None
    admin_detail=commerce_client.get(f"/api/v1/admin/rewards/{reward_id}",headers=admin).json()
    assert "private@example.test" in admin_detail["risk_flags"][0]["details"]
    detail = commerce_client.get("/api/v1/admin/rewards", headers=admin)
    assert detail.status_code == 200 and detail.json()["summary"]["actual_money_transferred"] is False
    reward_id = listing.json()["items"][0]["id"]
    assert commerce_client.post(f"/api/v1/admin/rewards/{reward_id}/approve", headers=admin, json={}).status_code == 409
    assert commerce_client.post(f"/api/v1/admin/rewards/{reward_id}/simulated-payout", headers=admin, json={}).status_code == 409
    assert commerce_client.post(f"/api/v1/admin/rewards/{reward_id}/approve", headers=brand, json={}).status_code == 403
    assert commerce_client.get("/api/v1/brand/reward-analytics", headers=brand).status_code == 200


def test_phase5_mixed_cart_creates_idempotent_item_attributed_rewards_for_multiple_creators(commerce_db, commerce_client):
    brand_a,_=create_account(commerce_db,"Brand A","phase5-mixed-brand-a@example.com","brand")
    brand_b,_=create_account(commerce_db,"Brand B","phase5-mixed-brand-b@example.com","brand")
    creator_a,creator_headers_a=create_account(commerce_db,"Creator A","phase5-mixed-creator-a@example.com","creator")
    creator_b,creator_headers_b=create_account(commerce_db,"Creator B","phase5-mixed-creator-b@example.com","creator")
    customer_id,customer=create_account(commerce_db,"Mixed Cart Customer","phase5-mixed-customer@example.com","customer")
    _admin_id,admin=create_account(commerce_db,"Mixed Cart Admin","phase5-mixed-admin@example.com","admin")
    product_a=create_product(commerce_db,brand_a,name="Product A",slug="phase5-product-a",sale_price=None)
    product_b=create_product(commerce_db,brand_b,name="Product B",slug="phase5-product-b",sale_price=None)
    with commerce_db() as db:
        campaign_a=Campaign(brand_id=brand_a,product_id=product_a,title="Campaign A",slug="phase5-campaign-a",description="",category="Beauty",platforms="Instagram",reward_model="percentage",reward_rate=Decimal("10"),budget=Decimal("5.00"),status="published")
        campaign_b=Campaign(brand_id=brand_b,product_id=product_b,title="Campaign B",slug="phase5-campaign-b",description="",category="Beauty",platforms="Instagram",reward_model="percentage",reward_rate=Decimal("20"),budget=Decimal("500"),status="published")
        db.add_all([campaign_a,campaign_b]);db.flush()
        db.add_all([Application(campaign_id=campaign_a.id,creator_id=creator_a,status="accepted"),Application(campaign_id=campaign_b.id,creator_id=creator_b,status="accepted"),Referral(campaign_id=campaign_a.id,creator_id=creator_a,code="MIXA",active=True),Referral(campaign_id=campaign_b.id,creator_id=creator_b,code="MIXB",active=True)])
        db.commit()
    assert commerce_client.get("/api/v1/r/MIXA").status_code==200
    assert add_to_cart(commerce_client,customer,product_a).status_code==201
    assert commerce_client.get("/api/v1/r/MIXB").status_code==200
    assert add_to_cart(commerce_client,customer,product_b).status_code==201
    order_response=commerce_client.post("/api/v1/checkout",headers={**customer,"Idempotency-Key":"phase5-multi-creator-cart"},json={**address(),"payment_method":"cod"})
    assert order_response.status_code==201
    with commerce_db() as db:
        order_before_collection=db.scalar(select(Order).where(Order.customer_id==customer_id))
        assert db.scalar(select(Reward.id).where(Reward.order_id==order_before_collection.id)) is None
    for status in ("processing","shipped","delivered"):
        assert commerce_client.patch(f"/api/v1/orders/{order_response.json()['id']}/status",headers=admin,json={"status":status}).status_code==200
    assert commerce_client.post(f"/api/v1/admin/orders/{order_response.json()['id']}/collect-payment",headers=admin).status_code==200
    with commerce_db() as db:
        order=db.scalar(select(Order).where(Order.customer_id==customer_id))
        rewards=db.scalars(select(Reward).where(Reward.order_id==order.id).order_by(Reward.creator_id)).all()
        assert len(rewards)==2 and {row.creator_id for row in rewards}=={creator_a,creator_b}
        assert len({row.source_key for row in rewards})==2
        assert all(not row.is_demo and row.status=="pending" for row in rewards)
        assert {row.product_id for row in rewards}=={product_a,product_b}
        assert {row.amount for row in rewards}=={Decimal("5.00"),Decimal("20.00")}
        capped=db.scalar(select(Reward).where(Reward.order_id==order.id,Reward.product_id==product_a))
        assert capped.calculation_snapshot["campaign_budget"]=="5.00" and capped.calculation_snapshot["campaign_budget_used_before"]=="0.00"
        items=db.scalars(select(OrderItem).where(OrderItem.order_id==order.id)).all()
        assert {item.referral_id for item in items}=={db.scalar(select(Referral.id).where(Referral.code=="MIXA")),db.scalar(select(Referral.id).where(Referral.code=="MIXB"))}
    for headers in (creator_headers_a,creator_headers_b):
        page=commerce_client.get("/api/v1/creator/rewards",headers=headers).json()
        assert page["total"]==1 and page["items"][0]["is_demo"] is False
        assert "customer_email" not in str(page) and "customer_id" not in str(page)
    replay=commerce_client.post("/api/v1/checkout",headers={**customer,"Idempotency-Key":"phase5-multi-creator-cart"},json={**address(),"payment_method":"demo"})
    assert replay.status_code==200
    with commerce_db() as db:
        assert db.scalar(select(func.count(Reward.id)))==2
        assert db.scalar(select(func.count(LedgerEntry.id)).where(LedgerEntry.entry_type=="REWARD_PENDING"))==2


def test_phase4_referral_link_click_mixed_cart_conversion_and_creator_analytics(commerce_db, commerce_client):
    brand_id, brand = create_account(commerce_db, "Noya", "phase4-brand@example.com", "brand")
    other_brand_id, other_brand = create_account(commerce_db, "Other", "phase4-other@example.com", "brand")
    creator_id, creator = create_account(commerce_db, "Jules Lane", "phase4-creator@example.com", "creator")
    customer_id, customer = create_account(commerce_db, "Customer", "phase4-customer@example.com", "customer")
    _admin_id, admin = create_account(commerce_db, "Admin", "phase4-admin@example.com", "admin")
    eligible_product = create_product(commerce_db, brand_id, sale_price=None, stock=5)
    unrelated_product = create_product(commerce_db, other_brand_id, sale_price=None, stock=5)
    campaign = commerce_client.post("/api/v1/campaigns", headers=brand, json={"title": "Spring Creator Edit", "product_ids": [eligible_product], "reward_rate": "10", "budget": "500"})
    assert campaign.status_code == 201
    campaign_id = campaign.json()["id"]
    assert commerce_client.patch(f"/api/v1/campaigns/{campaign_id}/status", headers=brand, json={"status": "published"}).status_code == 200
    application = commerce_client.post(f"/api/v1/campaigns/{campaign_id}/applications", headers=creator, json={"message": "Approved partner"})
    assert application.status_code == 201
    assert commerce_client.patch(f"/api/v1/applications/{application.json()['id']}", headers=brand, json={"status": "accepted"}).status_code == 200
    unapproved = create_account(commerce_db, "Unapproved", "phase4-unapproved@example.com", "creator")[1]
    assert commerce_client.post("/api/v1/referrals/links", headers=unapproved, json={"campaign_id": campaign_id}).status_code == 403
    assert commerce_client.post("/api/v1/referrals/links", headers=creator, json={"campaign_id": campaign_id, "product_id": unrelated_product}).status_code == 422
    generated = commerce_client.post("/api/v1/referrals/links", headers=creator, json={"campaign_id": campaign_id})
    assert generated.status_code == 201
    link = generated.json()
    assert link["creator_id"] == creator_id and link["campaign_id"] == campaign_id and link["code"]
    assert link["url"] == f"/r/{link['code']}"
    tracked = commerce_client.get(f"/api/v1/r/{link['code']}", headers={"referer": "https://social.example/post?private=1"})
    assert tracked.status_code == 200 and tracked.json()["destination"] == f"/shop?campaign_id={campaign_id}"
    assert "crownd_attribution=" in tracked.headers["set-cookie"]
    assert commerce_client.get(f"/api/v1/products/{eligible_product}").status_code == 200
    assert add_to_cart(commerce_client, customer, eligible_product).status_code == 201
    assert add_to_cart(commerce_client, customer, unrelated_product).status_code == 201
    order_response = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "phase4-mixed-demo-order"}, json={**address(), "payment_method": "demo"})
    assert order_response.status_code == 201
    assert order_response.json()["conversion"]["status"] == "confirmed"
    assert order_response.json()["conversion"]["is_demo"] is True
    with commerce_db() as db:
        stored = db.scalar(select(Order).where(Order.customer_id == customer_id))
        conversion = db.scalar(select(Conversion).where(Conversion.order_id == stored.id))
        items = db.scalars(select(OrderItem).where(OrderItem.order_id == stored.id).order_by(OrderItem.id)).all()
        assert conversion and conversion.creator_id == creator_id and conversion.campaign_id == campaign_id
        assert conversion.attributed_amount == Decimal("100.00")
        assert len(items) == 2 and sum(item.referral_id is not None for item in items) == 1
        assert db.scalar(select(func.count(Conversion.id)).where(Conversion.order_id == stored.id)) == 1
        assert db.scalar(select(func.count(ConversionEvent.id)).where(ConversionEvent.conversion_id == conversion.id)) == 2
        click = db.scalar(select(Click).where(Click.referral_id == conversion.referral_id))
        assert click.session_hash and len(click.session_hash) == 64
        assert click.referrer_origin == "social.example" and "private" not in (click.referrer_origin or "")
        assert db.scalar(select(func.count(ReferralActivity.id)).where(ReferralActivity.event_type == "product_view")) == 1
        demo_reward = db.scalar(select(Reward).where(Reward.order_id == stored.id))
        assert demo_reward and demo_reward.is_demo and demo_reward.amount == Decimal("10.00")
    metrics = commerce_client.get("/api/v1/creator/referral-analytics", headers=creator).json()["metrics"]
    assert metrics["clicks"] == 1 and metrics["unique_visitors"] == 1
    assert metrics["product_views"] == 1 and metrics["cart_additions"] == 1
    assert metrics["orders"] == 1 and metrics["confirmed_conversions"] == 1 and metrics["demo_conversions"] == 1
    creator_metrics=commerce_client.get(f"/api/v1/creator/referral-analytics?campaign_id={campaign_id}&product_id={eligible_product}&referral_id={link['id']}",headers=creator)
    assert creator_metrics.status_code==200 and creator_metrics.json()["metrics"]["confirmed_conversions"]==1
    creator_items=commerce_client.get(f"/api/v1/creator/conversions?campaign_id={campaign_id}&product_id={eligible_product}&referral_id={link['id']}",headers=creator)
    assert creator_items.status_code==200 and creator_items.json()["total"]==1
    assert "customer_email" not in creator_items.json()["items"][0] and "customer_id" not in creator_items.json()["items"][0]
    brand_metrics=commerce_client.get(f"/api/v1/brand/campaign-analytics/{campaign_id}?product_id={eligible_product}",headers=brand)
    assert brand_metrics.status_code==200 and brand_metrics.json()["metrics"]["confirmed_conversions"]==1
    admin_items=commerce_client.get(f"/api/v1/admin/conversions?q={link['code']}&creator_id={creator_id}&campaign_id={campaign_id}&product_id={eligible_product}",headers=admin)
    assert admin_items.status_code==200 and admin_items.json()["total"]==1
    admin_links=commerce_client.get(f"/api/v1/admin/referrals?creator_id={creator_id}&campaign_id={campaign_id}&product_id={eligible_product}",headers=admin)
    assert admin_links.status_code==200 and admin_links.json()["total"]==1
    assert commerce_client.get("/api/v1/creator/conversions", headers=creator).json()["total"] == 1
    replay = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "phase4-mixed-demo-order"}, json={**address(), "payment_method": "demo"})
    assert replay.status_code == 200
    with commerce_db() as db:
        assert db.scalar(select(func.count(Conversion.id))) == 1
    assert commerce_client.get("/api/v1/admin/referrals", headers=creator).status_code == 403


def test_phase4_cod_conversion_confirmed_only_after_collection_and_cancelled_history(commerce_db, commerce_client):
    brand_id, brand = create_account(commerce_db, "Noya", "cod-phase4-brand@example.com", "brand")
    _creator_id, creator = create_account(commerce_db, "Creator", "cod-phase4-creator@example.com", "creator")
    customer_id, customer = create_account(commerce_db, "Buyer", "cod-phase4-buyer@example.com", "customer")
    _admin_id, admin = create_account(commerce_db, "Admin", "cod-phase4-admin@example.com", "admin")
    product_id = create_product(commerce_db, brand_id, sale_price=None, stock=5)
    campaign = commerce_client.post("/api/v1/campaigns", headers=brand, json={"title": "COD Referral Campaign", "product_id": product_id, "reward_rate": "10", "budget": "1000"}).json()
    commerce_client.patch(f"/api/v1/campaigns/{campaign['id']}/status", headers=brand, json={"status": "published"})
    app = commerce_client.post(f"/api/v1/campaigns/{campaign['id']}/applications", headers=creator, json={}).json()
    commerce_client.patch(f"/api/v1/applications/{app['id']}", headers=brand, json={"status": "accepted"})
    link = commerce_client.post("/api/v1/referrals/links", headers=creator, json={"campaign_id": campaign["id"]}).json()
    commerce_client.get(f"/api/v1/r/{link['code']}")
    add_to_cart(commerce_client, customer, product_id)
    pending = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "phase4-cod-pending-001"}, json={**address(), "payment_method": "cod"})
    assert pending.status_code == 201 and pending.json()["conversion"]["status"] == "pending"
    with commerce_db() as db:
        order = db.scalar(select(Order).where(Order.customer_id == customer_id, Order.payment_method == "cod"))
        assert db.scalar(select(Reward.id).where(Reward.order_id == order.id)) is None
    for status in ("processing", "shipped", "delivered"):
        assert commerce_client.patch(f"/api/v1/orders/{pending.json()['id']}/status", headers=admin, json={"status": status}).status_code == 200
    assert commerce_client.post(f"/api/v1/admin/orders/{pending.json()['id']}/collect-payment", headers=admin).status_code == 200
    assert commerce_client.post(f"/api/v1/admin/orders/{pending.json()['id']}/collect-payment", headers=admin).status_code == 409
    with commerce_db() as db:
        order = db.scalar(select(Order).where(Order.customer_id == customer_id, Order.payment_method == "cod"))
        conversion = db.scalar(select(Conversion).where(Conversion.order_id == order.id))
        reward = db.scalar(select(Reward).where(Reward.order_id == order.id))
        assert conversion.status == "confirmed" and conversion.is_demo is False
        assert reward and reward.is_demo is False and reward.status == "pending"
        ledger = db.scalars(select(LedgerEntry).where(LedgerEntry.order_id == order.id)).all()
        assert len(ledger) == 1 and ledger[0].direction == "credit" and ledger[0].reward_id == reward.id
        assert db.scalar(select(func.count(ConversionEvent.id)).where(ConversionEvent.conversion_id == conversion.id)) == 2
    assert commerce_client.post(f"/api/v1/orders/{pending.json()['id']}/cancel", headers=customer).status_code == 409

    commerce_client.get(f"/api/v1/r/{link['code']}")
    add_to_cart(commerce_client, customer, product_id)
    cancelled = commerce_client.post("/api/v1/checkout", headers={**customer, "Idempotency-Key": "phase4-cod-cancel-001"}, json={**address(), "payment_method": "cod"})
    assert cancelled.status_code == 201 and cancelled.json()["conversion"]["status"] == "pending"
    assert commerce_client.post(f"/api/v1/orders/{cancelled.json()['id']}/cancel", headers=customer).status_code == 200
    with commerce_db() as db:
        order = db.scalar(select(Order).where(Order.idempotency_key == "phase4-cod-cancel-001"))
        conversion = db.scalar(select(Conversion).where(Conversion.order_id == order.id))
        assert conversion.status == "cancelled"
        assert db.scalar(select(func.count(ConversionEvent.id)).where(ConversionEvent.conversion_id == conversion.id)) == 2
        assert db.scalar(select(Reward.id).where(Reward.order_id == order.id)) is None


def test_phase4_link_deactivation_invalidates_click_and_preserves_history(commerce_db, commerce_client):
    brand_id, brand = create_account(commerce_db, "Brand", "deactivate-brand@example.com", "brand")
    _creator_id, creator = create_account(commerce_db, "Creator", "deactivate-creator@example.com", "creator")
    product_id = create_product(commerce_db, brand_id)
    campaign = commerce_client.post("/api/v1/campaigns", headers=brand, json={"title": "Deactivation campaign", "product_id": product_id}).json()
    commerce_client.patch(f"/api/v1/campaigns/{campaign['id']}/status", headers=brand, json={"status": "published"})
    application = commerce_client.post(f"/api/v1/campaigns/{campaign['id']}/applications", headers=creator, json={}).json()
    commerce_client.patch(f"/api/v1/applications/{application['id']}", headers=brand, json={"status": "accepted"})
    link = commerce_client.post("/api/v1/referrals/links", headers=creator, json={"campaign_id": campaign["id"]}).json()
    assert commerce_client.get(f"/api/v1/r/{link['code']}").status_code == 200
    assert commerce_client.patch(f"/api/v1/referrals/links/{link['id']}", headers=brand, json={"active": False}).status_code == 403
    assert commerce_client.patch(f"/api/v1/referrals/links/{link['id']}", headers=creator, json={"active": False}).status_code == 200
    assert commerce_client.get(f"/api/v1/r/{link['code']}").status_code == 410
    with commerce_db() as db:
        assert db.scalar(select(Referral).where(Referral.id == link["id"])).active is False
        assert db.scalar(select(func.count(Click.id)).where(Click.referral_id == link["id"])) == 2


def test_phase4_last_valid_referral_replaces_touch_without_direct_traffic_erasing_it(commerce_db, commerce_client):
    brand_id, brand = create_account(commerce_db, "Brand", "touch-brand@example.com", "brand")
    _creator_id, creator = create_account(commerce_db, "Creator", "touch-creator@example.com", "creator")
    _customer_id, customer = create_account(commerce_db, "Buyer", "touch-customer@example.com", "customer")
    product_one = create_product(commerce_db, brand_id, sale_price=None, stock=3)
    product_two = create_product(commerce_db, brand_id, name="Second Serum", slug="second-serum", sale_price=None, stock=3)
    links=[]
    for index,product_id in enumerate((product_one,product_two),start=1):
        campaign=commerce_client.post("/api/v1/campaigns",headers=brand,json={"title":f"Touch Campaign {index}","product_id":product_id}).json()
        commerce_client.patch(f"/api/v1/campaigns/{campaign['id']}/status",headers=brand,json={"status":"published"})
        application=commerce_client.post(f"/api/v1/campaigns/{campaign['id']}/applications",headers=creator,json={}).json()
        commerce_client.patch(f"/api/v1/applications/{application['id']}",headers=brand,json={"status":"accepted"})
        links.append(commerce_client.post("/api/v1/referrals/links",headers=creator,json={"campaign_id":campaign["id"]}).json())
    assert commerce_client.get(f"/api/v1/r/{links[0]['code']}").status_code == 200
    with commerce_db() as db:
        first_ref=db.scalar(select(Referral).where(Referral.id==links[0]["id"]))
        state=db.scalar(select(VisitorAttribution))
        first_hash=state.visitor_hash
        first_touch=state.first_touch_at
        assert state.first_referral_id==first_ref.id and state.last_referral_id==first_ref.id
    # Direct navigation, product views and cart activity do not erase or replace last touch.
    assert commerce_client.get(f"/api/v1/products/{product_one}").status_code==200
    assert commerce_client.get(f"/api/v1/r/{links[1]['code']}").status_code==200
    with commerce_db() as db:
        state=db.scalar(select(VisitorAttribution).where(VisitorAttribution.visitor_hash==first_hash))
        assert state.first_referral_id==links[0]["id"]
        assert state.last_referral_id==links[1]["id"]
        assert state.first_touch_at==first_touch
    add_to_cart(commerce_client,customer,product_two)
    order=commerce_client.post("/api/v1/checkout",headers={**customer,"Idempotency-Key":"phase4-last-touch-001"},json={**address(),"payment_method":"cod"})
    assert order.status_code==201 and order.json()["referral"]["code"]==links[1]["code"]
    with commerce_db() as db:
        stored=db.scalar(select(Order).where(Order.idempotency_key=="phase4-last-touch-001"))
        item=db.scalar(select(OrderItem).where(OrderItem.order_id==stored.id))
        conversion=db.scalar(select(Conversion).where(Conversion.order_id==stored.id))
        state=db.scalar(select(VisitorAttribution).where(VisitorAttribution.visitor_hash==first_hash))
        assert stored.referral_id==links[1]["id"] and item.referral_id==links[1]["id"]
        assert conversion.status=="pending" and conversion.referral_id==links[1]["id"]
        assert state.customer_id is not None


def test_phase4_self_referral_is_ineligible_and_flagged(commerce_db):
    from app.services.conversions import create_conversion
    brand_id,_brand=create_account(commerce_db,"Brand","self-brand@example.com","brand")
    creator_id,creator_headers=create_account(commerce_db,"Creator","self-creator@example.com","creator")
    product_id=create_product(commerce_db,brand_id)
    with commerce_db() as db:
        campaign=Campaign(brand_id=brand_id,product_id=product_id,title="Self referral",slug="self-referral",status="published")
        db.add(campaign);db.flush()
        db.add(Application(campaign_id=campaign.id,creator_id=creator_id,status="accepted"))
        referral=Referral(campaign_id=campaign.id,creator_id=creator_id,code="SELFTEST",active=True)
        db.add(referral)
        db.flush()
        order=Order(public_id="CR-SELFTEST001",customer_name="Creator",customer_email="self-creator@example.com",customer_id=creator_id,product_id=product_id,quantity=1,amount=Decimal("100.00"),currency="INR",payment_method="demo",payment_status="paid",status="confirmed")
        db.add(order);db.flush()
        conversion=create_conversion(db,order,referral,visitor_hash="a"*64,attributed_amount=Decimal("100.00"),eligible_product_count=1,customer=db.get(User,creator_id))
        db.commit()
        assert conversion.status=="ineligible" and conversion.reason=="self_referral" and conversion.attributed_amount==Decimal("0.00")
        assert db.scalar(select(ReferralRiskFlag).where(ReferralRiskFlag.risk_code=="SELF_REFERRAL")) is not None
        assert db.scalar(select(Reward).where(Reward.order_id==order.id)) is None
