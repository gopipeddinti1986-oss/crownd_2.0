"""Database-isolated API and auth regression tests."""
from datetime import timedelta, timezone, datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
from decimal import Decimal
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import auth as auth_routes
from app.api.v1.auth import limiter
from app.core.config import Settings, settings
from app.database import Base, get_db
from app.main import app
from app.models.entities import AuthActionToken, AuthSession, User
from app.security import ALGORITHM, create_access_token, hash_password
from app.services.auth import create_session
from app.services.rewards import calculate_reward

@pytest.fixture
def db_engine():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture
def client(db_engine,monkeypatch):
    TestingSession=sessionmaker(bind=db_engine,autoflush=False,expire_on_commit=False)
    def override_db():
        db=TestingSession()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override_db
    limiter.reset()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    limiter.reset()

@pytest.fixture
def emails(monkeypatch):
    sent=[]
    monkeypatch.setattr(auth_routes,"_attempt_email",lambda db,user,purpose,token: sent.append({"to":user.email,"purpose":purpose,"token":token}))
    return sent

def register(client,email="person@example.com",role="creator",name="Test Person",password="a-very-strong-password"):
    return client.post("/api/v1/auth/register",json={"name":name,"email":email,"password":password,"role":role,"username":email.split("@")[0],"brand_name":name})

def verified_login(client,emails,email="person@example.com",role="creator",name="Test Person",password="a-very-strong-password"):
    result=register(client,email,role,name,password)
    assert result.status_code==202,result.text
    matching=[item for item in emails if item["to"]==email and item["purpose"]=="verify_email"]
    assert matching
    verification=client.post("/api/v1/auth/email/verification/confirm",json={"token":matching[-1]["token"]})
    assert verification.status_code==200,verification.text
    logged=client.post("/api/v1/auth/login",json={"email":email,"password":password})
    assert logged.status_code==200,logged.text
    return logged.json(),{"Authorization":"Bearer "+logged.json()["access_token"]}

def test_registration_verification_required_and_passwords_are_argon2id(client,emails,db_engine):
    response=register(client)
    assert response.status_code==202
    assert "access_token" not in response.json()
    assert client.post("/api/v1/auth/login",json={"email":"person@example.com","password":"a-very-strong-password"}).status_code==403
    assert emails[-1]["purpose"]=="verify_email"
    with sessionmaker(bind=db_engine)() as db:
        user=db.scalar(select(User).where(User.email=="person@example.com"))
        assert user and not user.email_verified and user.password_hash.startswith("$argon2id$")
        action=db.scalar(select(AuthActionToken).where(AuthActionToken.user_id==user.id))
        assert action and action.token_hash!=emails[-1]["token"]

def test_login_invalid_credentials_unverified_and_legacy_hash_upgrade(client,emails,db_engine):
    register(client)
    assert client.post("/api/v1/auth/login",json={"email":"person@example.com","password":"wrong-password"}).status_code==401
    assert client.post("/api/v1/auth/login",json={"email":"absent@example.com","password":"wrong-password"}).status_code==401
    with sessionmaker(bind=db_engine)() as db:
        user=db.scalar(select(User).where(User.email=="person@example.com"))
        salt="legacy-salt"
        user.password_hash=f"{salt}${hashlib.pbkdf2_hmac('sha256',b'a-very-strong-password',salt.encode(),180_000).hex()}"
        user.email_verified=True
        db.commit()
    response=client.post("/api/v1/auth/login",json={"email":"person@example.com","password":"a-very-strong-password"})
    assert response.status_code==200
    with sessionmaker(bind=db_engine)() as db:
        assert db.scalar(select(User).where(User.email=="person@example.com")).password_hash.startswith("$argon2id$")

def test_refresh_cookie_rotation_expiration_attributes_and_revocation(client,emails):
    data,_=verified_login(client,emails)
    old_cookie=client.cookies.get("crownd_refresh")
    assert old_cookie and old_cookie not in data.values()
    set_cookie=client.cookies.get("crownd_refresh")
    response=client.post("/api/v1/auth/refresh")
    assert response.status_code==200
    new_cookie=client.cookies.get("crownd_refresh")
    assert new_cookie and new_cookie!=old_cookie
    header=response.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/api/v1/auth" in header
    assert "secure" not in header # local development only
    # Replaying the old secret revokes the session and the new access token immediately stops working.
    client.cookies.set("crownd_refresh",old_cookie,path="/api/v1/auth")
    replay=client.post("/api/v1/auth/refresh")
    assert replay.status_code==401
    assert client.get("/api/v1/auth/me",headers={"Authorization":"Bearer "+response.json()["access_token"]}).status_code==401

def test_forged_refresh_cookie_cannot_revoke_known_session(client,emails):
    data,headers=verified_login(client,emails)
    session_id=jwt.decode(data["access_token"],settings.jwt_secret,algorithms=[ALGORITHM])["sid"]
    client.cookies.set("crownd_refresh",f"{session_id}.attacker-forged-secret.invalid-mac",path="/api/v1/auth")
    response=client.post("/api/v1/auth/refresh")
    assert response.status_code==401
    assert client.get("/api/v1/auth/me",headers=headers).status_code==200

def test_logout_all_revokes_all_user_sessions(client,emails):
    data,headers=verified_login(client,emails)
    second=client.post("/api/v1/auth/login",json={"email":"person@example.com","password":"a-very-strong-password"})
    assert second.status_code==200
    assert client.post("/api/v1/auth/logout-all",headers={"Authorization":"Bearer "+second.json()["access_token"]}).status_code==204
    assert client.get("/api/v1/auth/me",headers=headers).status_code==401
    assert client.get("/api/v1/auth/me",headers={"Authorization":"Bearer "+second.json()["access_token"]}).status_code==401

def test_logout_revokes_access_and_refresh(client,emails):
    data,headers=verified_login(client,emails)
    assert client.get("/api/v1/auth/me",headers=headers).status_code==200
    response=client.post("/api/v1/auth/logout",headers=headers)
    assert response.status_code==204
    assert client.get("/api/v1/auth/me",headers=headers).status_code==401
    assert client.post("/api/v1/auth/refresh").status_code==401

def test_access_token_expiration_and_unknown_session(client,emails):
    data,_=verified_login(client,emails)
    session_id=jwt.decode(data["access_token"],settings.jwt_secret,algorithms=[ALGORITHM])["sid"]
    expired=jwt.encode({"sub":"1","sid":session_id,"iat":datetime.now(timezone.utc)-timedelta(minutes=5),"exp":datetime.now(timezone.utc)-timedelta(minutes=1),"jti":"expired-test"},settings.jwt_secret,algorithm=ALGORITHM)
    assert client.get("/api/v1/auth/me",headers={"Authorization":"Bearer "+expired}).status_code==401

def test_refresh_session_expiry(client,emails,db_engine):
    data,_=verified_login(client,emails)
    session_id=jwt.decode(data["access_token"],settings.jwt_secret,algorithms=[ALGORITHM])["sid"]
    with sessionmaker(bind=db_engine)() as db:
        session=db.get(AuthSession,session_id)
        session.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert client.post("/api/v1/auth/refresh").status_code==401

def test_password_reset_token_expiry(client,emails,db_engine):
    verified_login(client,emails)
    client.post("/api/v1/auth/password/reset/request",json={"email":"person@example.com"})
    token=next(item["token"] for item in reversed(emails) if item["purpose"]=="password_reset")
    with sessionmaker(bind=db_engine)() as db:
        record=db.scalar(select(AuthActionToken).where(AuthActionToken.purpose=="password_reset"))
        record.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert client.post("/api/v1/auth/password/reset/confirm",json={"token":token,"new_password":"another-strong-new-password"}).status_code==400

def test_password_reset_is_generic_one_time_and_revokes_sessions(client,emails):
    data,headers=verified_login(client,emails)
    existing=client.post("/api/v1/auth/password/reset/request",json={"email":"person@example.com"})
    missing=client.post("/api/v1/auth/password/reset/request",json={"email":"not-here@example.com"})
    assert existing.status_code==missing.status_code==202
    assert existing.json()["message"]==missing.json()["message"]
    token=next(item["token"] for item in reversed(emails) if item["purpose"]=="password_reset")
    reset=client.post("/api/v1/auth/password/reset/confirm",json={"token":token,"new_password":"brand-new-strong-password"})
    assert reset.status_code==200
    assert client.post("/api/v1/auth/password/reset/confirm",json={"token":token,"new_password":"another-new-strong-password"}).status_code==400
    assert client.get("/api/v1/auth/me",headers=headers).status_code==401
    assert client.post("/api/v1/auth/login",json={"email":"person@example.com","password":"brand-new-strong-password"}).status_code==200

def test_email_verification_expiry_and_replay(client,emails,db_engine):
    register(client)
    token=emails[-1]["token"]
    with sessionmaker(bind=db_engine)() as db:
        record=db.scalar(select(AuthActionToken).where(AuthActionToken.purpose=="verify_email"))
        record.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert client.post("/api/v1/auth/email/verification/confirm",json={"token":token}).status_code==400
    # Issuing a new link consumes older outstanding links; successful link is one-use.
    request=client.post("/api/v1/auth/email/verification/request",json={"email":"person@example.com"})
    assert request.status_code==202
    fresh=emails[-1]["token"]
    assert client.post("/api/v1/auth/email/verification/confirm",json={"token":fresh}).status_code==200
    assert client.post("/api/v1/auth/email/verification/confirm",json={"token":fresh}).status_code==400

def test_role_and_cross_user_authorization_and_no_auth(client,emails):
    brand_data,brand=verified_login(client,emails,"brand@example.com","brand","Brand")
    creator_data,creator=verified_login(client,emails,"creator@example.com","creator","Creator")
    other_data,other=verified_login(client,emails,"other@example.com","brand","Other Brand")
    assert client.get("/api/v1/auth/me").status_code==401
    assert client.post("/api/v1/products",headers=creator,json={"name":"Nope","price":10}).status_code==403
    product=client.post("/api/v1/products",headers=brand,json={"name":"Brand Product","price":"12.00","stock":2})
    assert product.status_code==201
    campaign=client.post("/api/v1/campaigns",headers=brand,json={"title":"Owned Campaign","product_id":product.json()["id"]})
    assert campaign.status_code==201
    assert client.patch(f"/api/v1/campaigns/{campaign.json()['id']}/status",headers=other,json={"status":"published"}).status_code==403
    assert client.get(f"/api/v1/ai/matches/{campaign.json()['id']}",headers=other).status_code==403
    assert client.get("/api/v1/admin/users",headers=brand).status_code==403

def test_validation_and_trusted_origin(client,emails,monkeypatch):
    invalid=client.post("/api/v1/auth/register",json={"name":"X","email":"bad","password":"short","role":"admin"})
    assert invalid.status_code==422
    _,headers=verified_login(client,emails)
    rejected=client.post("/api/v1/auth/logout",headers={**headers,"Origin":"https://attacker.example"})
    assert rejected.status_code==403
    assert client.get("/api/v1/auth/me",headers=headers).status_code==200
    monkeypatch.setattr(settings,"trusted_proxy_ips","127.0.0.1,::1,testclient")
    monkeypatch.setattr(settings,"app_env","production")
    production_rejected=client.post("/api/v1/auth/logout",headers={**headers,"Origin":"https://preview.example","X-Forwarded-Host":"preview.example"})
    assert production_rejected.status_code==403
    monkeypatch.setattr(settings,"app_env","development")
    allowed=client.post("/api/v1/auth/logout",headers={**headers,"Origin":"https://preview.example","X-Forwarded-Host":"preview.example"})
    assert allowed.status_code==204

def test_authentication_rate_limit(client):
    responses=[client.post("/api/v1/auth/login",json={"email":"nobody@example.com","password":"incorrect"}) for _ in range(9)]
    assert all(item.status_code==401 for item in responses[:8])
    assert responses[8].status_code==429

def test_production_configuration_fails_closed():
    common={"app_env":"production","jwt_secret":"a"*48,"email_mode":"smtp","smtp_host":"mail.example",
        "cors_origins":"https://crownd.example","frontend_base_url":"https://crownd.example",
        "rate_limit_storage_uri":"rediss://redis.example:6380/0","trusted_proxy_ips":"10.1.0.2",
        "forwarded_allow_ips":"10.1.0.2","trusted_hosts":"crownd.example,api.crownd.example"}
    with pytest.raises(ValueError):
        Settings(app_env="production",jwt_secret="short",email_mode="disabled")
    with pytest.raises(ValueError):
        Settings(**{**common,"rate_limit_storage_uri":"memory://"})
    with pytest.raises(ValueError):
        Settings(**{**common,"rate_limit_storage_uri":"redis://redis.example:6379/0"})
    with pytest.raises(ValueError):
        Settings(**{**common,"cookie_secure":False,"cookie_samesite":"none"})
    with pytest.raises(ValueError):
        Settings(**{**common,"database_url":"postgresql+psycopg://app:secret@db/crownd"})
    with pytest.raises(ValueError):
        Settings(**{**common,"database_url":"postgresql+psycopg://app:secret@db/crownd?sslmode=require","trusted_hosts":"*"})
    with pytest.raises(ValueError):
        Settings(**{**common,"forwarded_allow_ips":"*"})
    with pytest.raises(ValueError):
        Settings(**{**common,"forwarded_allow_ips":"not-an-ip"})
    safe=Settings(**{**common,"database_url":"postgresql+psycopg://app:secret@db/crownd?sslmode=verify-full"})
    assert safe.use_secure_cookies is True

def test_readiness_request_id_and_security_headers(client, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="crownd.api")
    response=client.get("/api/v1/health/ready?token=phase10-query-secret",headers={"X-Request-ID":"phase10-check_01"})
    assert response.status_code==200 and response.json()=={"status":"ready","dependencies":{"database":"ok"}}
    assert response.headers["x-request-id"]=="phase10-check_01"
    assert response.headers["x-content-type-options"]=="nosniff"
    assert response.headers["x-frame-options"]=="DENY"
    assert response.headers["permissions-policy"]=="camera=(), microphone=(), geolocation=()"
    assert "phase10-query-secret" not in caplog.text
    bad_host=client.get("/api/v1/health/live",headers={"host":"attacker.example"})
    assert bad_host.status_code==400


def test_readiness_database_failure_is_generic(client):
    from sqlalchemy.exc import OperationalError
    original=app.dependency_overrides[get_db]
    def broken_db():
        class BrokenSession:
            def execute(self,_statement):
                raise OperationalError("SELECT 1",{},Exception("secret database detail"))
        yield BrokenSession()
    app.dependency_overrides[get_db]=broken_db
    try:
        response=client.get("/api/v1/health/ready")
        assert response.status_code==503
        assert "secret database detail" not in response.text
        assert "DATABASE_URL" not in response.text
    finally:
        app.dependency_overrides[get_db]=original


def test_development_email_provider_reports_no_delivery(monkeypatch):
    from app.services.email import DisabledEmailProvider, OutgoingEmail
    monkeypatch.setattr(settings,"email_mode","disabled")
    assert DisabledEmailProvider().send(OutgoingEmail("person@example.com","Subject","body")) is False

def test_decimal_reward_calculations():
    assert calculate_reward(Decimal("2000.00"),"percentage",Decimal("10"))==Decimal("200.00")
    assert calculate_reward(Decimal("19.99"),"percentage",Decimal("12.5"))==Decimal("2.50")
    assert calculate_reward(Decimal("2000"),"fixed",Decimal("35.50"))==Decimal("35.50")

def test_campaign_application_referral_order_and_reward(client,emails):
    _,brand=verified_login(client,emails,"brandflow@test.example","brand","Flow Brand")
    _,creator=verified_login(client,emails,"creatorflow@test.example","creator","Flow Creator")
    product=client.post("/api/v1/products",headers=brand,json={"name":"Daily Oil","price":"2000.00","stock":10}).json()
    camp=client.post("/api/v1/campaigns",headers=brand,json={"title":"Everyday Ritual","product_id":product["id"],"reward_rate":10,"budget":10000}).json()
    assert client.patch(f"/api/v1/campaigns/{camp['id']}/status",headers=brand,json={"status":"published"}).status_code==200
    assert client.post(f"/api/v1/campaigns/{camp['id']}/applications",headers=creator,json={"message":"Love the product"}).status_code==201
    applications=client.get("/api/v1/applications",headers=brand).json()
    assert len(applications)==1
    brand_notices=client.get("/api/v1/notifications",headers=brand).json()["items"]
    assert any(item["title"]=="Campaign application received" for item in brand_notices)
    assert client.patch(f"/api/v1/applications/{applications[0]['id']}",headers=brand,json={"status":"accepted"}).status_code==200
    creator_notices=client.get("/api/v1/notifications",headers=creator).json()["items"]
    assert any(item["title"]=="Application update" for item in creator_notices)
    ref=client.get("/api/v1/referrals/me",headers=creator).json()[0]
    assert client.get(f"/api/v1/r/{ref['code']}").status_code==200
    assert client.post("/api/v1/orders",json={"customer_name":"Guest","customer_email":"guest@example.com","product_id":product["id"],"quantity":1,"simulate_payment":True}).status_code==410
    _,customer=verified_login(client,emails,"customerflow@test.example","customer","Flow Customer")
    assert client.post("/api/v1/cart/items",headers=customer,json={"product_id":product["id"],"quantity":1}).status_code==201
    address={"name":"Flow Customer","phone":"+91 98765 43210","line1":"12 Market Road","city":"Rajamahendravaram","state":"Andhra Pradesh","postal_code":"533101","country":"IN"}
    order=client.post("/api/v1/checkout",headers={**customer,"Idempotency-Key":"campaign-demo-order-001"},json={"shipping_address":address,"payment_method":"demo"})
    assert order.status_code==201 and order.json()["payment_status"]=="paid" and order.json()["payment_method"]=="demo"
    reward=client.get("/api/v1/rewards/me",headers=creator).json()
    assert len(reward)==1 and reward[0]["amount"]==200.0 and reward[0]["status"]=="simulated" and reward[0]["is_demo"] is True and reward[0]["payable"] is False
    customer_notices=client.get("/api/v1/notifications",headers=customer).json()["items"]
    assert any("No real money was charged" in item["body"] for item in customer_notices)
    creator_notices=client.get("/api/v1/notifications",headers=creator).json()["items"]
    assert any("not payable" in item["body"] and "no money was transferred" in item["body"] for item in creator_notices)

def test_campaign_duplicate_application_prevented(client,emails):
    _,brand=verified_login(client,emails,"dupbrand@test.example","brand","Dup Brand")
    _,creator=verified_login(client,emails,"dupcreator@test.example","creator","Dup Creator")
    campaign=client.post("/api/v1/campaigns",headers=brand,json={"title":"Duplicate Guard"}).json()
    client.patch(f"/api/v1/campaigns/{campaign['id']}/status",headers=brand,json={"status":"published"})
    assert client.post(f"/api/v1/campaigns/{campaign['id']}/applications",headers=creator,json={}).status_code==201
    assert client.post(f"/api/v1/campaigns/{campaign['id']}/applications",headers=creator,json={}).status_code==409


def test_concurrent_refresh_requests_cannot_both_rotate_the_same_secret(tmp_path, monkeypatch):
    engine=create_engine(f"sqlite:///{tmp_path/'refresh-race.db'}",connect_args={"check_same_thread":False,"timeout":15})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
    def override_db():
        db=factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override_db
    limiter.reset()
    with factory() as db:
        user=User(name="Race User",email="refresh-race@example.test",role="customer",
            password_hash=hash_password("unused-test-password"),email_verified=True,is_active=True)
        db.add(user);db.flush()
        session,raw=create_session(db,user);db.commit();session_id=session.id
    original=auth_routes.verify_refresh_secret
    gate=Barrier(2)
    def synchronized_verify(value):
        result=original(value)
        if result: gate.wait(timeout=8)
        return result
    monkeypatch.setattr(auth_routes,"verify_refresh_secret",synchronized_verify)
    try:
        with TestClient(app) as test_client:
            def refresh():
                return test_client.post("/api/v1/auth/refresh",headers={"Cookie":f"crownd_refresh={raw}"})
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses=[future.result(timeout=20) for future in [pool.submit(refresh),pool.submit(refresh)]]
        assert sorted(response.status_code for response in responses)==[200,401]
        with factory() as db:
            assert db.get(AuthSession,session_id).revoked_at is not None
    finally:
        app.dependency_overrides.clear();limiter.reset();engine.dispose()


def test_creator_profile_update_validates_fields_bounds_ownership_and_missing_records(client,emails,db_engine):
    _,creator=verified_login(client,emails,"profile-update@test.example","creator","Profile Creator")
    _,other_creator=verified_login(client,emails,"profile-other@test.example","creator","Other Creator")
    _,brand=verified_login(client,emails,"profile-brand@test.example","brand","Profile Brand")
    endpoint="/api/v1/creators/me"

    assert client.put(endpoint,headers=creator,json={"followers":1234,"engagement":4.2,"bio":"A useful bio"}).json()["profile"]["followers"]==1234
    listed=client.get("/api/v1/creators",headers=brand,params={"q":"Profile Creator"})
    assert listed.status_code==200 and listed.json()[0]["bio"]=="A useful bio"
    assert client.get("/api/v1/creators",headers=brand,params={"q":"Instagram"}).json()[0]["username"]=="profile-update"
    assert client.get("/api/v1/creators",headers=brand,params={"q":"x"*121}).status_code==422
    assert client.put(endpoint,headers=creator,json={"unknown":"value"}).status_code==422
    assert client.put(endpoint,headers=creator,json={"followers":-1}).status_code==422
    assert client.put(endpoint,headers=creator,json={"engagement":100.01}).status_code==422
    assert client.put(endpoint,headers=creator,json={"username":"invalid name"}).status_code==422
    assert client.put(endpoint,headers=creator,json={"followers":"not-a-number"}).status_code==422
    assert client.put(endpoint,headers=creator,json={"name":None}).status_code==422
    assert client.put(endpoint,headers=creator,json={}).status_code==422
    assert client.put(endpoint,headers=brand,json={"bio":"not a creator"}).status_code==403
    assert client.put(endpoint,headers=other_creator,json={"username":"profile-update"}).status_code==409

    from sqlalchemy import select
    from app.models.entities import CreatorProfile
    with sessionmaker(bind=db_engine)() as db:
        profile=db.scalar(select(CreatorProfile).where(CreatorProfile.username=="profile-update"))
        assert profile is not None
        db.delete(profile)
        db.commit()
    assert client.put(endpoint,headers=creator,json={"bio":"profile missing"}).status_code==404


def test_role_aware_account_profile_updates_are_validated_and_audited(client,emails,db_engine):
    _,creator=verified_login(client,emails,"account-profile-creator@test.example","creator","Creator Before")
    _,brand=verified_login(client,emails,"account-profile-brand@test.example","brand","Brand Before")
    _,customer=verified_login(client,emails,"account-profile-customer@test.example","customer","Customer Before")
    with sessionmaker(bind=db_engine,autoflush=False,expire_on_commit=False)() as db:
        admin_user=User(name="Admin Before",email="account-profile-admin@test.example",role="admin",password_hash=hash_password("admin-testing-password"),email_verified=True)
        db.add(admin_user);db.flush();admin_session,_secret=create_session(db,admin_user);db.commit()
        admin={"Authorization":"Bearer "+create_access_token(admin_user,admin_session.id)}

    updated_creator=client.put("/api/v1/me/profile",headers=creator,json={"name":"Creator After","bio":"An updated creator bio","followers":3050})
    assert updated_creator.status_code==200
    assert updated_creator.json()["name"]=="Creator After" and updated_creator.json()["profile"]["followers"]==3050
    assert client.put("/api/v1/me/profile",headers=creator,json={"industry":"Not allowed for creators"}).status_code==422
    assert client.put("/api/v1/me/profile",headers=creator,json={"engagement":100.1}).status_code==422
    assert client.put("/api/v1/me/profile",headers=creator,json={"unknown":"field"}).status_code==422
    assert client.put("/api/v1/me/profile",headers=creator,json={"bio":None}).status_code==422

    updated_brand=client.put("/api/v1/me/profile",headers=brand,json={"name":"New Brand Name","industry":"Food","website":"https://brand.example","description":"Updated profile"})
    assert updated_brand.status_code==200 and updated_brand.json()["profile"]["industry"]=="Food"
    assert client.put("/api/v1/me/profile",headers=brand,json={"website":"http://unsafe.example"}).status_code==422
    assert client.put("/api/v1/me/profile",headers=brand,json={"website":"https://bad example.test"}).status_code==422
    assert client.put("/api/v1/me/profile",headers=brand,json={"website":"https://user:pass@example.test"}).status_code==422
    updated_customer=client.put("/api/v1/me/profile",headers=customer,json={"name":"Customer After"})
    assert updated_customer.status_code==200 and updated_customer.json()["name"]=="Customer After"
    assert client.put("/api/v1/me/profile",headers=customer,json={"bio":"Not editable"}).status_code==422
    assert client.put("/api/v1/me/profile",headers=admin,json={"name":"Admin After"}).status_code==200
    assert client.put("/api/v1/me/profile",headers=creator,json={}).status_code==422

    from sqlalchemy import select,func
    from app.models.entities import AuditLog
    with sessionmaker(bind=db_engine)() as db:
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action=="account.profile_updated"))==4


def test_creator_can_withdraw_pending_application_once_and_cannot_withdraw_accepted(client,emails,db_engine):
    from sqlalchemy import func
    from app.models.entities import Application, AuditLog, Notification, Referral

    _,brand=verified_login(client,emails,"withdraw-brand@test.example","brand","Withdraw Brand")
    _,creator=verified_login(client,emails,"withdraw-creator@test.example","creator","Withdraw Creator")
    _,other_creator=verified_login(client,emails,"withdraw-other@test.example","creator","Other Creator")
    campaign=client.post("/api/v1/campaigns",headers=brand,json={"title":"Withdrawal campaign"}).json()
    assert client.patch(f"/api/v1/campaigns/{campaign['id']}/status",headers=brand,json={"status":"published"}).status_code==200
    path=f"/api/v1/campaigns/{campaign['id']}/applications"
    submitted=client.post(path,headers=creator,json={"message":"Please consider me"})
    assert submitted.status_code==201
    app_id=submitted.json()["id"]
    withdraw_url=f"/api/v1/applications/{app_id}/withdraw"
    assert client.post(withdraw_url,headers=other_creator).status_code==404
    assert client.post(withdraw_url,headers=brand).status_code==403
    first=client.post(withdraw_url,headers=creator)
    assert first.status_code==200 and first.json()["status"]=="withdrawn"
    replay=client.post(withdraw_url,headers=creator)
    assert replay.status_code==200 and replay.json()["status"]=="withdrawn"
    assert client.patch(f"/api/v1/applications/{app_id}",headers=brand,json={"status":"accepted"}).status_code==409
    with sessionmaker(bind=db_engine)() as db:
        row=db.get(Application,app_id)
        brand_id=db.scalar(select(User.id).where(User.email=="withdraw-brand@test.example"))
        assert row.status=="withdrawn"
        assert db.scalar(select(func.count(Notification.id)).where(
            Notification.recipient_id==brand_id,
            Notification.event_key==f"application-withdrawn:{app_id}"))==1
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.actor_id==row.creator_id,
            AuditLog.action=="application.withdrawn",AuditLog.entity_id==str(app_id)))==1
        assert not db.scalar(select(Referral.id).where(Referral.campaign_id==campaign["id"],
            Referral.creator_id==row.creator_id,Referral.active.is_(True)))

    accepted_app=client.post(path,headers=other_creator,json={"message":"I am available"})
    assert accepted_app.status_code==201
    assert client.patch(f"/api/v1/applications/{accepted_app.json()['id']}",headers=brand,json={"status":"accepted"}).status_code==200
    assert client.post(f"/api/v1/applications/{accepted_app.json()['id']}/withdraw",headers=other_creator).status_code==409
    with sessionmaker(bind=db_engine)() as db:
        active_referral=db.scalar(select(Referral).where(Referral.campaign_id==campaign["id"],
            Referral.creator_id==db.scalar(select(User.id).where(User.email=="withdraw-other@test.example"))))
        assert active_referral and active_referral.active is True


def test_application_payload_validation_owner_checks_and_idempotent_review(client,emails,db_engine):
    _,brand=verified_login(client,emails,"application-brand@test.example","brand","Application Brand")
    _,other_brand=verified_login(client,emails,"application-other-brand@test.example","brand","Other Brand")
    _,creator=verified_login(client,emails,"application-creator@test.example","creator","Application Creator")
    campaign=client.post("/api/v1/campaigns",headers=brand,json={"title":"Application schema campaign"}).json()
    assert client.patch(f"/api/v1/campaigns/{campaign['id']}/status",headers=brand,json={"status":"published"}).status_code==200
    apply_url=f"/api/v1/campaigns/{campaign['id']}/applications"
    assert client.post(apply_url,headers=creator,json={"message":"x"*2001}).status_code==422
    assert client.post(apply_url,headers=creator,json={"message":"ok","status":"accepted"}).status_code==422
    submitted=client.post(apply_url,headers=creator,json={"message":"Please consider my work."})
    assert submitted.status_code==201
    assert client.post(apply_url,headers=creator,json={}).status_code==409

    review_url=f"/api/v1/applications/{submitted.json()['id']}"
    assert client.patch("/api/v1/applications/999999",headers=brand,json={"status":"accepted"}).status_code==404
    assert client.patch(review_url,headers=creator,json={"status":"accepted"}).status_code==403
    assert client.patch(review_url,headers=other_brand,json={"status":"accepted"}).status_code==403
    assert client.patch(review_url,headers=brand,json={"status":"unknown"}).status_code==422
    assert client.patch(review_url,headers=brand,json={"status":"accepted","reason":"extra"}).status_code==422

    accepted=client.patch(review_url,headers=brand,json={"status":"accepted"})
    assert accepted.status_code==200 and accepted.json()["status"]=="accepted"
    from sqlalchemy import select,func
    from app.models.entities import AuditLog,Notification,Referral,User
    with sessionmaker(bind=db_engine)() as db:
        creator_id=db.scalar(select(User.id).where(User.email=="application-creator@test.example"))
        referral_count=db.scalar(select(func.count(Referral.id)).where(Referral.campaign_id==campaign["id"]))
        notification_count=db.scalar(select(func.count(Notification.id)).where(Notification.recipient_id==creator_id))
        audit_count=db.scalar(select(func.count(AuditLog.id)).where(AuditLog.entity_type=="application",AuditLog.entity_id==str(submitted.json()["id"])))
    # A retried request for the current state is a no-op: it emits no second referral/audit/notice.
    assert client.patch(review_url,headers=brand,json={"status":"accepted"}).status_code==200
    assert client.patch(review_url,headers=brand,json={"status":"rejected"}).status_code==409
    with sessionmaker(bind=db_engine)() as db:
        assert db.scalar(select(func.count(Referral.id)).where(Referral.campaign_id==campaign["id"]))==referral_count==1
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.entity_type=="application",AuditLog.entity_id==str(submitted.json()["id"])))==audit_count==1
        assert db.scalar(select(func.count(Notification.id)).where(Notification.recipient_id==creator_id))==notification_count==2
