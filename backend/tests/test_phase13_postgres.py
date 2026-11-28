"""Opt-in Phase 13 concurrency/migration checks for a disposable PostgreSQL DB.

These tests deliberately skip unless both an explicit URL and an explicit
operator acknowledgment are provided. They create and drop only a random,
private schema; the target database must itself be disposable.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import re
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.api.v1.auth import limiter
from app.core.config import settings
from app.database import get_db
from app.main import app
from app.models.entities import AdminDispute, Application, Campaign, Cart, CartItem, Conversion, LedgerEntry, Order, OrderItem, Product, Referral, Reward, User
from app.security import create_access_token
from app.services.auth import create_session


URL_ENV = "CROWND_PHASE13_DISPOSABLE_POSTGRES_URL"
ACK_ENV = "CROWND_PHASE13_POSTGRES_ACK"


@pytest.fixture(scope="module")
def disposable_postgres():
    raw_url = os.getenv(URL_ENV)
    if not raw_url:
        pytest.skip(f"Set {URL_ENV} to an approved disposable PostgreSQL database to run concurrency tests")
    if os.getenv(ACK_ENV) != "I_AM_USING_A_DISPOSABLE_DATABASE":
        pytest.fail(f"Refusing PostgreSQL integration tests without {ACK_ENV}=I_AM_USING_A_DISPOSABLE_DATABASE")
    base_url = make_url(raw_url)
    if not base_url.drivername.startswith("postgresql"):
        pytest.fail(f"{URL_ENV} must use PostgreSQL; no URL value is printed")
    db_name = (base_url.database or "").lower()
    if not db_name or not re.search(r"(?:test|disposable|phase13)", db_name):
        pytest.fail("Disposable database name must contain 'test', 'disposable', or 'phase13'")

    schema = "phase13_" + uuid4().hex
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = base_url.update_query_dict({"options": f"-csearch_path={schema}"})
    old_database_url = settings.database_url
    settings.database_url = scoped_url.render_as_string(hide_password=False)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    scoped_engine = create_engine(scoped_url, pool_pre_ping=True, pool_size=8, max_overflow=4)
    factory = sessionmaker(bind=scoped_engine, autoflush=False, expire_on_commit=False)

    try:
        # Exercise the actual 0010 upgrade from a 0009-shaped schema rather than
        # relying on current ORM metadata to create the new columns in revision 0001.
        command.upgrade(config, "0009_notifications")
        with scoped_engine.begin() as connection:
            connection.execute(text("ALTER TABLE order_items DROP COLUMN reward_snapshot"))
            connection.execute(text("ALTER TABLE rewards DROP COLUMN dispute_hold"))
            connection.execute(text("ALTER TABLE rewards DROP COLUMN dispute_prior_status"))
        command.upgrade(config, "head")

        def override_db():
            yield from _yield_db(factory)

        app.dependency_overrides[get_db] = override_db
        yield {"engine": scoped_engine, "factory": factory, "config": config, "schema": schema}
    finally:
        app.dependency_overrides.pop(get_db, None)
        limiter.reset()
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
        settings.database_url = old_database_url


def _yield_db(factory):
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _account(factory, role: str, suffix: str) -> tuple[int, dict[str, str]]:
    with factory() as db:
        user = User(name=f"PG {role} {suffix}", email=f"{role}-{suffix}@phase13.test",
                    password_hash="test-only-unused", role=role, is_active=True, email_verified=True)
        db.add(user)
        db.flush()
        session, _refresh = create_session(db, user)
        db.commit()
        token = create_access_token(user, session.id)
        return user.id, {"Authorization": f"Bearer {token}"}


def _product(factory, brand_id: int, stock: int = 3) -> int:
    with factory() as db:
        row = Product(brand_id=brand_id, name="PG stock item", slug=f"pg-stock-{uuid4().hex}",
                      price="100.00", stock=stock, status="active")
        db.add(row)
        db.commit()
        return row.id


def _address():
    return {"shipping_address": {"name": "PG buyer", "phone": "+91 99999 11111", "line1": "1 Test Road",
        "city": "Rajamahendravaram", "state": "Andhra Pradesh", "postal_code": "533101", "country": "IN"}}


def test_phase13_postgres_0010_upgrade_downgrade_trigger_and_rollback(disposable_postgres):
    factory = disposable_postgres["factory"]
    engine = disposable_postgres["engine"]
    config = disposable_postgres["config"]
    brand_id, _ = _account(factory, "brand", "migration")
    customer_id, _ = _account(factory, "customer", "migration")
    product_id = _product(factory, brand_id)
    with factory() as db:
        order = Order(public_id=f"PG-{uuid4().hex[:12]}", customer_name="PG buyer", customer_email="pg-buyer@phase13.test",
                      customer_id=customer_id, product_id=product_id, quantity=1, amount="100.00",
                      payment_method="cod", payment_status="unpaid", status="confirmed")
        db.add(order)
        db.flush()
        item = OrderItem(order_id=order.id, product_id=product_id, product_name="PG stock item", brand_name="PG brand",
                         unit_price="100.00", quantity=1, line_total="100.00", reward_snapshot={"version": 1})
        db.add(item)
        db.commit()
        item_id, order_id = item.id, order.id

    with engine.connect() as connection:
        columns = set(connection.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='order_items'")).all())
        reward_columns = set(connection.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='rewards'")).all())
        assert "reward_snapshot" in columns
        assert {"dispute_hold", "dispute_prior_status"} <= reward_columns
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE order_items SET line_total=0 WHERE id=:id"), {"id": item_id})
        connection.rollback()
        with pytest.raises(DBAPIError):
            connection.execute(text("DELETE FROM order_items WHERE id=:id"), {"id": item_id})
        connection.rollback()
    with factory() as db:
        assert db.get(OrderItem, item_id).line_total == 100
    rollback_slug = f"pg-rollback-{uuid4().hex}"
    with pytest.raises(RuntimeError, match="force rollback"):
        with factory.begin() as db:
            db.add(Product(brand_id=brand_id, name="Rolled back", slug=rollback_slug, price="10.00", stock=1))
            db.flush()
            raise RuntimeError("force rollback")
    with factory() as db:
        assert db.scalar(select(Product.id).where(Product.slug == rollback_slug)) is None

    # Downgrade is intentionally non-destructive: it preserves snapshot/hold data
    # and the append-only trigger so historical records remain protected.
    command.downgrade(config, "0009_notifications")
    command.upgrade(config, "head")
    with factory() as db:
        assert db.get(Order, order_id) is not None
        assert db.get(OrderItem, item_id).reward_snapshot == {"version": 1}


def test_phase13_postgres_competing_last_item_checkouts_do_not_oversell(disposable_postgres):
    factory = disposable_postgres["factory"]
    brand_id, _ = _account(factory, "brand", "stock-race")
    _customer_a_id, customer_a = _account(factory, "customer", "stock-a")
    _customer_b_id, customer_b = _account(factory, "customer", "stock-b")
    product_id = _product(factory, brand_id, stock=1)
    limiter.reset()
    with TestClient(app) as client:
        assert client.post("/api/v1/cart/items", headers=customer_a, json={"product_id": product_id, "quantity": 1}).status_code == 201
        assert client.post("/api/v1/cart/items", headers=customer_b, json={"product_id": product_id, "quantity": 1}).status_code == 201

        def place(headers, key):
            return client.post("/api/v1/checkout", headers={**headers, "Idempotency-Key": key},
                               json={**_address(), "payment_method": "cod"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda args: place(*args), [
                (customer_a, "pg-last-item-customer-a"), (customer_b, "pg-last-item-customer-b")]))
    assert sorted(response.status_code for response in responses) == [201, 409]
    with factory() as db:
        product = db.get(Product, product_id)
        assert product.stock == 0
        assert db.scalar(select(func.count(Order.id)).where(Order.product_id == product_id)) == 1
        order = db.scalar(select(Order).where(Order.product_id == product_id))
        assert db.scalar(select(func.sum(OrderItem.quantity)).where(OrderItem.order_id == order.id)) == 1


def test_phase13_postgres_concurrent_cart_and_attributed_checkout_are_idempotent(disposable_postgres):
    factory = disposable_postgres["factory"]
    brand_id, brand_headers = _account(factory, "brand", "cart-race")
    creator_id, _creator_headers = _account(factory, "creator", "attribution-race")
    _customer_id, customer_headers = _account(factory, "customer", "same-key")
    product_id = _product(factory, brand_id, stock=8)
    with factory() as db:
        campaign = Campaign(brand_id=brand_id, product_id=product_id, title="PG attributed campaign",
                            slug=f"pg-campaign-{uuid4().hex}", description="", category="Other", platforms="Instagram",
                            reward_model="percentage", reward_rate="10", budget="1000", status="published")
        db.add(campaign)
        db.flush()
        db.add_all([Application(campaign_id=campaign.id, creator_id=creator_id, status="accepted"),
                    Referral(campaign_id=campaign.id, creator_id=creator_id, code=f"PG{uuid4().hex[:8]}", active=True)])
        db.commit()
        code = db.scalar(select(Referral.code).where(Referral.campaign_id == campaign.id))

    limiter.reset()
    with TestClient(app) as client:
        def add_one(_):
            return client.post("/api/v1/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        with ThreadPoolExecutor(max_workers=2) as pool:
            cart_responses = list(pool.map(add_one, range(2)))
        assert [response.status_code for response in cart_responses] == [201, 201]
        with factory() as db:
            assert db.scalar(select(func.count(Cart.id)).where(Cart.user_id == _customer_id)) == 1
            assert db.scalar(select(CartItem.quantity).join(Cart, Cart.id == CartItem.cart_id).where(Cart.user_id == _customer_id)) == 2
        assert client.get(f"/api/v1/r/{code}").status_code == 200
        # Rebuild a single-item cart after the two concurrent adds, then race the
        # same checkout key. The first response creates the order; the replay must
        # not decrement stock or duplicate conversions/rewards/ledger entries.
        assert client.delete("/api/v1/cart", headers=customer_headers).status_code == 204
        assert client.post("/api/v1/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1}).status_code == 201

        def checkout(_):
            return client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "pg-same-order-key-001"},
                               json={**_address(), "payment_method": "demo"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(checkout, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 201]
    with factory() as db:
        orders = db.scalars(select(Order).where(Order.customer_id == _customer_id)).all()
        assert len(orders) == 1
        assert db.scalar(select(func.count(Conversion.id)).where(Conversion.order_id == orders[0].id)) == 1
        rewards = db.scalars(select(Reward).where(Reward.order_id == orders[0].id)).all()
        assert len(rewards) == 1 and rewards[0].creator_id == creator_id
        assert db.scalar(select(func.count(LedgerEntry.id)).where(LedgerEntry.reward_id == rewards[0].id)) == 1
        assert db.get(Product, product_id).stock == 7


def test_phase13_postgres_competing_disputes_hold_until_last_resolution(disposable_postgres):
    factory = disposable_postgres["factory"]
    brand_id, _ = _account(factory, "brand", "dispute-race")
    creator_id, _ = _account(factory, "creator", "dispute-race")
    _customer_id, customer_headers = _account(factory, "customer", "dispute-race")
    _admin_id, admin_headers = _account(factory, "admin", "dispute-race")
    product_id = _product(factory, brand_id, stock=4)
    with factory() as db:
        campaign = Campaign(brand_id=brand_id, product_id=product_id, title="PG dispute campaign",
                            slug=f"pg-dispute-{uuid4().hex}", description="", category="Other", platforms="Instagram",
                            reward_model="percentage", reward_rate="10", budget="1000", status="published")
        db.add(campaign)
        db.flush()
        db.add_all([Application(campaign_id=campaign.id, creator_id=creator_id, status="accepted"),
                    Referral(campaign_id=campaign.id, creator_id=creator_id, code=f"PD{uuid4().hex[:8]}", active=True)])
        db.commit()
        code = db.scalar(select(Referral.code).where(Referral.campaign_id == campaign.id))

    limiter.reset()
    with TestClient(app) as client:
        assert client.get(f"/api/v1/r/{code}").status_code == 200
        assert client.post("/api/v1/cart/items", headers=customer_headers,
                           json={"product_id": product_id, "quantity": 1}).status_code == 201
        placed = client.post("/api/v1/checkout", headers={**customer_headers, "Idempotency-Key": "pg-dispute-order-001"},
                             json={**_address(), "payment_method": "cod"})
        assert placed.status_code == 201
        for status in ("processing", "shipped", "delivered"):
            assert client.patch(f"/api/v1/orders/{placed.json()['id']}/status", headers=admin_headers,
                                json={"status": status}).status_code == 200
        assert client.post(f"/api/v1/admin/orders/{placed.json()['id']}/collect-payment", headers=admin_headers).status_code == 200
        with factory() as db:
            order = db.scalar(select(Order).where(Order.public_id == placed.json()["id"]))
            reward = db.scalar(select(Reward).where(Reward.order_id == order.id))
            order_pk, reward_pk = order.id, reward.id
            assert reward.is_demo is False and reward.status == "pending"

        def open_case(_):
            return client.post("/api/v1/admin/disputes", headers=admin_headers, json={
                "reward_id": reward_pk, "summary": "Concurrent reward dispute", "reason": "Review attributed order evidence"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            cases = list(pool.map(open_case, range(2)))
        assert [response.status_code for response in cases] == [201, 201]
        case_ids = [response.json()["id"] for response in cases]
        with factory() as db:
            assert db.get(Reward, reward_pk).dispute_hold is True
            assert db.scalar(select(func.count(AdminDispute.id)).where(AdminDispute.reward_id == reward_pk,
                                                                         AdminDispute.status != "resolved")) == 2

        first_resolution = client.post(f"/api/v1/admin/disputes/{case_ids[0]}/status", headers=admin_headers, json={
            "status": "resolved", "reason": "First case resolved", "confirmation": "RESOLVED"})
        assert first_resolution.status_code == 200
        with factory() as db:
            still_held = db.get(Reward, reward_pk)
            assert still_held.dispute_hold is True and still_held.status == "under_review"
        second_resolution = client.post(f"/api/v1/admin/disputes/{case_ids[1]}/status", headers=admin_headers, json={
            "status": "resolved", "reason": "Final case resolved", "confirmation": "RESOLVED"})
        assert second_resolution.status_code == 200
    with factory() as db:
        released = db.get(Reward, reward_pk)
        assert released.dispute_hold is False and released.status == "pending"
        assert db.get(Order, order_pk) is not None
        assert db.scalar(select(func.count(LedgerEntry.id)).where(LedgerEntry.reward_id == reward_pk)) == 1
