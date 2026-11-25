import os
os.environ["JWT_SECRET"]="test-secret-not-for-production"
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import Base, get_db
from app.services.rewards import calculate_reward
from decimal import Decimal

engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
TestSession=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
Base.metadata.create_all(engine)
def override_db():
    db=TestSession()
    try: yield db
    finally: db.close()
app.dependency_overrides[get_db]=override_db
client=TestClient(app)
def auth(role="brand",email="brand@test.example",name="Test Brand"):
    r=client.post("/api/v1/auth/register",json={"name":name,"email":email,"password":"strong-password-123","role":role,"brand_name":name,"username":email.split('@')[0]})
    assert r.status_code==201,r.text
    return {"Authorization":"Bearer "+r.json()["access_token"]}
def test_decimal_reward_calculations():
    assert calculate_reward(Decimal("2000.00"),"percentage",Decimal("10"))==Decimal("200.00")
    assert calculate_reward(Decimal("19.99"),"percentage",Decimal("12.5"))==Decimal("2.50")
    assert calculate_reward(Decimal("2000"),"fixed",Decimal("35.50"))==Decimal("35.50")
def test_registration_and_role_authorization():
    creator=auth("creator","creator@test.example","Casey Creator")
    assert client.get("/api/v1/auth/me",headers=creator).json()["role"]=="creator"
    assert client.post("/api/v1/products",headers=creator,json={"name":"No","price":10}).status_code==403
    assert client.post("/api/v1/auth/register",json={"name":"X","email":"creator@test.example","password":"strong-password-123","role":"creator"}).status_code==409
def test_campaign_application_referral_order_and_reward():
    brand=auth("brand","brandflow@test.example","Flow Brand")
    creator=auth("creator","creatorflow@test.example","Flow Creator")
    product=client.post("/api/v1/products",headers=brand,json={"name":"Daily Oil","price":"2000.00","stock":10}).json()
    camp=client.post("/api/v1/campaigns",headers=brand,json={"title":"Everyday Ritual","product_id":product["id"],"reward_rate":10,"budget":10000}).json()
    assert client.patch(f"/api/v1/campaigns/{camp['id']}/status",headers=brand,json={"status":"published"}).status_code==200
    assert client.post(f"/api/v1/campaigns/{camp['id']}/applications",headers=creator,json={"message":"Love the product"}).status_code==201
    applications=client.get("/api/v1/applications",headers=brand).json()
    assert len(applications)==1
    assert client.patch(f"/api/v1/applications/{applications[0]['id']}",headers=brand,json={"status":"accepted"}).status_code==200
    ref=client.get("/api/v1/referrals/me",headers=creator).json()[0]
    assert client.get(f"/api/v1/r/{ref['code']}").status_code==200
    order=client.post("/api/v1/orders",json={"customer_name":"Customer","customer_email":"customer@example.com","product_id":product["id"],"quantity":1,"referral_code":ref["code"],"simulate_payment":True})
    assert order.status_code==201,order.text
    assert order.json()["payment_status"]=="paid"
    reward=client.get("/api/v1/rewards/me",headers=creator).json()
    assert len(reward)==1 and reward[0]["amount"]==200.0 and reward[0]["status"]=="pending"
def test_campaign_duplicate_application_prevented():
    brand=auth("brand","dupbrand@test.example","Dup Brand")
    creator=auth("creator","dupcreator@test.example","Dup Creator")
    campaign=client.post("/api/v1/campaigns",headers=brand,json={"title":"Duplicate Guard"}).json()
    client.patch(f"/api/v1/campaigns/{campaign['id']}/status",headers=brand,json={"status":"published"})
    assert client.post(f"/api/v1/campaigns/{campaign['id']}/applications",headers=creator,json={}).status_code==201
    assert client.post(f"/api/v1/campaigns/{campaign['id']}/applications",headers=creator,json={}).status_code==409
