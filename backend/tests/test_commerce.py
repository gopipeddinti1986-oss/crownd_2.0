from datetime import datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api.v1.auth import limiter
from app.database import Base, get_db
from app.main import app
from app.models.entities import BrandProfile, Campaign, Cart, CartItem, Order, OrderItem, Product, Referral, User
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
    first = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": key}, json=address())
    assert first.status_code == 201, first.text
    order = first.json()
    assert order["amount"] == "160.00" and order["payment_status"] == "pending" and order["status"] == "pending"
    assert order["items"][0]["unit_price"] == "80.00" and order["items"][0]["quantity"] == 2
    replay = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": key}, json=address())
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
    first = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "inventory-order-0001"}, json=address())
    assert first.status_code == 201
    second = commerce_client.post("/api/v1/checkout", headers={**other_headers, "Idempotency-Key": "inventory-order-0002"}, json=address())
    assert second.status_code == 409
    assert commerce_client.get("/api/v1/cart", headers=other_headers).json()["unavailable_count"] == 1
    assert commerce_client.get(f"/api/v1/orders/{first.json()['id']}", headers=other_headers).status_code == 404
    assert commerce_client.post(f"/api/v1/orders/{first.json()['id']}/cancel", headers=other_headers).status_code == 404
    cancelled = commerce_client.post(f"/api/v1/orders/{first.json()['id']}/cancel", headers=customer_headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert commerce_client.get("/api/v1/products", params={"brand_id": brand}).json()["items"][0]["stock"] == 2
    assert commerce_client.post(f"/api/v1/orders/{first.json()['id']}/cancel", headers=customer_headers).status_code == 409
    assert commerce_client.patch(f"/api/v1/orders/{first.json()['id']}/status", headers=brand_headers, json={"status": "processing"}).status_code == 409


def test_referral_cookie_attribution_is_signed_and_validated_at_checkout(commerce_db, commerce_client):
    brand, _ = create_account(commerce_db, "Noya", "brand@example.com", "brand")
    customer_id, customer_headers = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    creator_id, _ = create_account(commerce_db, "Jules Lane", "creator@example.com", "creator")
    product_id = create_product(commerce_db, brand)
    with commerce_db() as db:
        campaign = Campaign(brand_id=brand, product_id=product_id, title="Ritual", slug="ritual", description="", category="Beauty", platforms="Instagram", reward_model="percentage", reward_rate=Decimal("10"), budget=Decimal("1000"), status="published")
        db.add(campaign)
        db.flush()
        referral = Referral(campaign_id=campaign.id, creator_id=creator_id, code="JULES10", active=True)
        db.add(referral)
        db.commit()
    tracked = commerce_client.get("/api/v1/r/JULES10")
    assert tracked.status_code == 200 and "crownd_referral=" in tracked.headers["set-cookie"]
    assert tracked.json()["destination"] == f"/products/{product_id}"
    assert add_to_cart(commerce_client, customer_headers, product_id).status_code == 201
    created = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "referral-order-0001"}, json=address())
    assert created.status_code == 201 and created.json()["referral"]["creator_name"] == "Jules Lane"
    with commerce_db() as db:
        order = db.scalar(select(Order).where(Order.customer_id == customer_id))
        assert order.referral_id is not None
    # Tampering with the attribution cookie cannot assign an arbitrary referral.
    commerce_client.cookies.set("crownd_referral", "1.9999999999.forged")
    assert add_to_cart(commerce_client, customer_headers, product_id).status_code == 201
    uncredited = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "tampered-referral-001"}, json=address())
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
    customer_id, customer_headers = create_account(commerce_db, "Customer", "customer@example.com", "customer")
    product_id = create_product(commerce_db, brand, stock=1, sale_price=None)
    assert add_to_cart(commerce_client, customer_headers, product_id, 2).status_code == 409
    assert add_to_cart(commerce_client, customer_headers, product_id).status_code == 201
    order = commerce_client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "lifecycle-order-0001"}, json=address()).json()
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=brand_headers, json={"status": "confirmed"}).status_code == 200
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=brand_headers, json={"status": "processing"}).status_code == 409
    with commerce_db() as db:
        stored = db.scalar(select(Order).where(Order.public_id == order["id"]))
        stored.payment_status = "paid"  # Represents an upstream verified payment; no public endpoint can set this.
        db.commit()
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=brand_headers, json={"status": "processing"}).status_code == 200
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=brand_headers, json={"status": "shipped"}).status_code == 200
    assert commerce_client.patch(f"/api/v1/orders/{order['id']}/status", headers=brand_headers, json={"status": "delivered"}).status_code == 200
    assert commerce_client.post(f"/api/v1/orders/{order['id']}/cancel", headers=customer_headers).status_code == 409
