from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.api.v1.auth import limiter
from app.database import Base,get_db
from app.main import app
from app.models.entities import Application, Campaign, Click, Conversion, Order, OrderItem, Product, Referral, Reward
from app.security import create_access_token
from app.services.auth import create_session
from test_commerce import create_account, create_product


@pytest.fixture
def commerce_db():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine);engine.dispose()


@pytest.fixture
def commerce_client(commerce_db):
    def override_db():
        db=commerce_db()
        try:yield db
        finally:db.close()
    app.dependency_overrides[get_db]=override_db;limiter.reset()
    from fastapi.testclient import TestClient
    with TestClient(app) as client:yield client
    app.dependency_overrides.clear();limiter.reset()


def seed_campaign_activity(db_factory):
    brand_id,brand_headers=create_account(db_factory,"Analytics Brand","analytics-brand@example.com","brand")
    other_brand_id,other_headers=create_account(db_factory,"Other Analytics Brand","other-analytics-brand@example.com","brand")
    creator_id,creator_headers=create_account(db_factory,"Measured Creator","measured-creator@example.com","creator")
    _customer_id,customer_headers=create_account(db_factory,"Analytics Customer","analytics-customer@example.com","customer")
    _admin_id,admin_headers=create_account(db_factory,"Analytics Admin","analytics-admin@example.com","admin")
    product_id=create_product(db_factory,brand_id,name="Measured Product",slug="measured-product",sale_price=None)
    other_product_id=create_product(db_factory,other_brand_id,name="Private Product",slug="private-product",sale_price=None)
    now=datetime.now(timezone.utc)
    with db_factory() as db:
        campaign=Campaign(brand_id=brand_id,product_id=product_id,title="Measured Campaign",slug="measured-campaign",description="Actual data",category="Beauty",platforms="Instagram",reward_model="percentage",reward_rate=Decimal("10"),budget=Decimal("1000.00"),status="published",starts_at=now-timedelta(days=10),ends_at=now+timedelta(days=10),objectives=["Confirmed sales"],target_audience="Skincare shoppers",creator_requirements="Create original content",visibility="public",performance_goals={"confirmed_conversions":"2"})
        db.add(campaign);db.flush()
        referral=Referral(campaign_id=campaign.id,creator_id=creator_id,code="PHASE6ANALYTICS",active=True,product_id=product_id)
        db.add_all([referral,Application(campaign_id=campaign.id,creator_id=creator_id,status="accepted")]);db.flush()
        orders=[]
        order_data=[("CONF",Decimal("50.00"),"cod","paid","delivered","confirmed",False),("PEND",Decimal("30.00"),"cod","unpaid","delivered","pending",False),("DEMO",Decimal("20.00"),"demo","paid","delivered","confirmed",True),("CANCEL",Decimal("10.00"),"cod","unpaid","cancelled","cancelled",False)]
        for label,amount,method,payment,status,conversion_status,is_demo in order_data:
            order=Order(public_id=f"PA6-{label}",customer_name="Private Customer",customer_email="private-customer@example.test",product_id=product_id,quantity=1,amount=amount,referral_id=referral.id,payment_status=payment,payment_method=method,currency="INR",status=status,created_at=now)
            db.add(order);db.flush()
            db.add(OrderItem(order_id=order.id,product_id=product_id,product_name="Measured Product",brand_name="Analytics Brand",unit_price=amount,quantity=1,line_total=amount,referral_id=referral.id))
            db.add(Conversion(order_id=order.id,referral_id=referral.id,creator_id=creator_id,campaign_id=campaign.id,visitor_hash=f"visitor-{label}",status=conversion_status,attributed_amount=amount,currency="INR",is_demo=is_demo,created_at=now,confirmed_at=now if conversion_status=="confirmed" else None))
            orders.append(order)
        for session_hash in ("visitor-hash-1","visitor-hash-1","", "visitor-hash-2"):
            db.add(Click(referral_id=referral.id,clicked_at=now,session_hash=session_hash,status="valid"))
        db.add_all([Reward(order_id=orders[0].id,creator_id=creator_id,brand_id=brand_id,campaign_id=campaign.id,conversion_id=None,referral_id=referral.id,order_item_id=None,product_id=product_id,amount=Decimal("5.00"),eligible_amount=Decimal("50.00"),excluded_amount=Decimal("0.00"),currency="INR",status="pending",eligible_at=now+timedelta(days=30),is_demo=False,created_at=now),Reward(order_id=orders[2].id,creator_id=creator_id,brand_id=brand_id,campaign_id=campaign.id,referral_id=referral.id,product_id=product_id,amount=Decimal("2.00"),eligible_amount=Decimal("20.00"),excluded_amount=Decimal("0.00"),currency="INR",status="simulated",eligible_at=now+timedelta(days=30),is_demo=True,created_at=now),Reward(order_id=orders[1].id,creator_id=creator_id,brand_id=brand_id,campaign_id=campaign.id,referral_id=referral.id,product_id=product_id,amount=Decimal("3.00"),eligible_amount=Decimal("30.00"),excluded_amount=Decimal("0.00"),currency="INR",status="pending_collection",eligible_at=now+timedelta(days=30),is_demo=False,created_at=now)])
        db.commit();campaign_id=campaign.id
    return {"brand_id":brand_id,"brand":brand_headers,"other_brand":other_headers,"creator_id":creator_id,"creator":creator_headers,"customer":customer_headers,"admin":admin_headers,"campaign_id":campaign_id,"product_id":product_id,"other_product_id":other_product_id}


def test_brand_campaign_analytics_uses_item_attribution_and_separates_payment_states(commerce_db,commerce_client):
    data=seed_campaign_activity(commerce_db)
    response=commerce_client.get("/api/v1/brand/analytics/campaigns/"+str(data["campaign_id"]),headers=data["brand"],params={"period":"lifetime"})
    assert response.status_code==200,response.text
    body=response.json();metrics=body["metrics"]
    assert metrics["clicks"]==4 and metrics["unique_visitors"]==2
    assert metrics["orders"]==4 and metrics["confirmed_orders"]==1 and metrics["pending_orders"]==1
    assert metrics["cancelled_orders"]==1 and metrics["reversed_orders"]==0 and metrics["simulated_orders"]==1
    assert metrics["gross_attributed_order_value"]=="110.00"
    assert metrics["confirmed_revenue"]=="50.00" and metrics["pending_revenue"]=="30.00"
    assert metrics["cancelled_revenue"]=="10.00" and metrics["simulated_revenue"]=="20.00"
    assert metrics["generated_reward_value"]=="8.00" and metrics["simulated"]=="2.00"
    assert metrics["pending_collection"]=="3.00"
    assert metrics["roi"]["available"] is False and metrics["roi"]["roi_pct"] is None
    assert metrics["reward_efficiency"]["ratio"]=="6.25"
    assert "customer_email" not in str(body) and "Private Customer" not in str(body)
    assert body["campaign"]["creator_count"]==1 and body["campaign"]["active_creators"]==1
    assert any(item["product_id"]==data["product_id"] and item["confirmed_revenue"]=="50.00" for item in body["products"])
    assert any(item["creator_id"]==data["creator_id"] and item["confirmed_revenue"]=="50.00" for item in body["creators"])


def test_analytics_role_ownership_date_validation_and_empty_windows(commerce_db,commerce_client):
    data=seed_campaign_activity(commerce_db)
    endpoint=f"/api/v1/brand/analytics/campaigns/{data['campaign_id']}"
    assert commerce_client.get(endpoint,headers=data["other_brand"]).status_code==404
    assert commerce_client.get("/api/v1/brand/analytics/overview",headers=data["creator"]).status_code==403
    assert commerce_client.get("/api/v1/admin/analytics/overview",headers=data["brand"]).status_code==403
    admin_report=commerce_client.get("/api/v1/admin/analytics/overview",headers=data["admin"])
    assert admin_report.status_code==200 and admin_report.json()["customer_data_excluded"] is True
    assert admin_report.json()["campaigns"]["comparison"][0]["campaign_id"]==data["campaign_id"]
    assert admin_report.json()["creators"]["generating_confirmed_conversions"]==1
    assert commerce_client.get(endpoint,headers=data["brand"],params={"period":"custom","start_date":"2026-10-20","end_date":"2026-10-01"}).status_code==422
    assert commerce_client.get(endpoint,headers=data["brand"],params={"period":"custom","start_date":"2026-10-01"}).status_code==422
    empty=commerce_client.get(endpoint,headers=data["brand"],params={"period":"custom","start_date":"2030-01-01","end_date":"2030-01-02"})
    assert empty.status_code==200 and empty.json()["metrics"]["confirmed_revenue"]=="0.00"


def test_campaign_management_lifecycle_and_brand_ownership(commerce_db,commerce_client):
    data=seed_campaign_activity(commerce_db)
    campaign_id=data["campaign_id"]
    listed=commerce_client.get("/api/v1/brand/campaigns",headers=data["brand"],params={"q":"Measured","status":"published"})
    assert listed.status_code==200 and listed.json()["total"]==1
    assert commerce_client.get("/api/v1/brand/campaigns",headers=data["other_brand"]).json()["total"]==0
    detail=commerce_client.get(f"/api/v1/brand/campaigns/{campaign_id}",headers=data["other_brand"])
    assert detail.status_code==404
    assert commerce_client.patch(f"/api/v1/campaigns/{campaign_id}/status",headers=data["brand"],json={"status":"paused"}).status_code==200
    assert commerce_client.patch(f"/api/v1/campaigns/{campaign_id}/status",headers=data["brand"],json={"status":"published"}).status_code==200
    assert commerce_client.patch(f"/api/v1/campaigns/{campaign_id}/status",headers=data["brand"],json={"status":"draft"}).status_code==422
    assert commerce_client.patch(f"/api/v1/campaigns/{campaign_id}/status",headers=data["other_brand"],json={"status":"paused"}).status_code==403
    updated=commerce_client.put(f"/api/v1/campaigns/{campaign_id}",headers=data["brand"],json={"title":"Updated measured campaign","objectives":["More confirmed sales"],"performance_goals":{"confirmed_conversions":3}})
    assert updated.status_code==409
    assert commerce_client.patch(f"/api/v1/campaigns/{campaign_id}/status",headers=data["brand"],json={"status":"paused"}).status_code==200
    updated=commerce_client.put(f"/api/v1/campaigns/{campaign_id}",headers=data["brand"],json={"title":"Updated measured campaign","objectives":["More confirmed sales"],"performance_goals":{"confirmed_conversions":3}})
    assert updated.status_code==200 and updated.json()["objectives"]==["More confirmed sales"]
    catalog_scope=commerce_client.put(f"/api/v1/campaigns/{campaign_id}",headers=data["brand"],json={"product_ids":[]})
    assert catalog_scope.status_code==200 and catalog_scope.json()["product_ids"]==[] and len(catalog_scope.json()["products"])==1
    rejected=commerce_client.patch(f"/api/v1/campaigns/{campaign_id}/status",headers=data["admin"],json={"status":"rejected"})
    assert rejected.status_code==409
    rejected=commerce_client.post(f"/api/v1/admin/campaigns/{campaign_id}/moderation",headers=data["admin"],json={"status":"rejected","reason":"Campaign violates published policy","confirmation":"REJECTED"})
    assert rejected.status_code==200 and rejected.json()["status"]=="rejected"


def test_brand_analytics_csv_export_escapes_formula_and_excludes_pii(commerce_db,commerce_client):
    data=seed_campaign_activity(commerce_db)
    with commerce_db() as db:
        campaign=db.get(Campaign,data["campaign_id"]);campaign.title="=HYPERLINK(\"https://evil.test\")";db.commit()
    response=commerce_client.get("/api/v1/brand/analytics/export",headers=data["brand"],params={"kind":"campaigns","period":"lifetime"})
    assert response.status_code==200 and response.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK" in response.text
    assert "private-customer@example.test" not in response.text and "Private Customer" not in response.text
    assert commerce_client.get("/api/v1/brand/analytics/export",headers=data["other_brand"],params={"kind":"campaigns"}).text.count("\r\n")==1


def test_campaign_create_structured_configuration_visibility_and_validation(commerce_db,commerce_client):
    data=seed_campaign_activity(commerce_db)
    created=commerce_client.post("/api/v1/campaigns",headers=data["brand"],json={"title":"Unlisted launch","description":"Brief","product_id":data["product_id"],"product_ids":[data["product_id"]],"objectives":["Awareness","Confirmed orders"],"target_audience":"Sensitive skin customers","creator_requirements":"Original video","visibility":"unlisted","performance_goals":{"confirmed_conversions":5},"starts_at":"2026-01-01T00:00:00Z","ends_at":"2026-02-01T00:00:00Z"})
    assert created.status_code==201,created.text
    campaign_id=created.json()["id"]
    detail=commerce_client.get(f"/api/v1/brand/campaigns/{campaign_id}",headers=data["brand"])
    assert detail.status_code==200 and detail.json()["visibility"]=="unlisted"
    assert detail.json()["objectives"]==["Awareness","Confirmed orders"]
    assert detail.json()["performance_goals"]["confirmed_conversions"]=="5"
    assert commerce_client.get("/api/v1/campaigns",params={"q":"Unlisted launch","status":"all"}).json()==[]
    invalid=commerce_client.post("/api/v1/campaigns",headers=data["brand"],json={"title":"Bad goal","performance_goals":{"followers":100}})
    assert invalid.status_code==422
    invalid_dates=commerce_client.post("/api/v1/campaigns",headers=data["brand"],json={"title":"Bad dates","starts_at":"2026-02-01T00:00:00Z","ends_at":"2026-01-01T00:00:00Z"})
    assert invalid_dates.status_code==422


def test_mixed_cart_revenue_is_split_by_attributed_order_item_without_double_count(commerce_db,commerce_client):
    data=seed_campaign_activity(commerce_db)
    creator_b,_=create_account(commerce_db,"Second Creator","second-analytics-creator@example.com","creator")
    product_b=create_product(commerce_db,data["brand_id"],name="Second Product",slug="second-analytics-product",sale_price=None,price=Decimal("100.00"))
    now=datetime.now(timezone.utc)
    with commerce_db() as db:
        campaign_a=db.get(Campaign,data["campaign_id"])
        campaign_b=Campaign(brand_id=data["brand_id"],product_id=product_b,title="Second Campaign",slug="second-analytics-campaign",description="",category="Beauty",platforms="Instagram",reward_model="percentage",reward_rate=Decimal("10"),budget=Decimal("100"),status="published",starts_at=now-timedelta(days=5),ends_at=now+timedelta(days=5))
        db.add(campaign_b);db.flush()
        referral_a=db.scalar(select(Referral).where(Referral.campaign_id==campaign_a.id))
        referral_b=Referral(campaign_id=campaign_b.id,creator_id=creator_b,code="PHASE6MIXEDB",active=True,product_id=product_b)
        db.add_all([referral_b,Application(campaign_id=campaign_b.id,creator_id=creator_b,status="accepted")]);db.flush()
        order=Order(public_id="PA6-MIXED",customer_name="Private",customer_email="private@example.test",product_id=data["product_id"],quantity=2,amount=Decimal("150.00"),referral_id=referral_a.id,payment_status="paid",payment_method="cod",currency="INR",status="delivered",created_at=now)
        db.add(order);db.flush()
        db.add_all([OrderItem(order_id=order.id,product_id=data["product_id"],product_name="Measured Product",brand_name="Analytics Brand",unit_price=Decimal("50.00"),quantity=1,line_total=Decimal("50.00"),referral_id=referral_a.id),OrderItem(order_id=order.id,product_id=product_b,product_name="Second Product",brand_name="Analytics Brand",unit_price=Decimal("100.00"),quantity=1,line_total=Decimal("100.00"),referral_id=referral_b.id),Conversion(order_id=order.id,referral_id=referral_a.id,creator_id=data["creator_id"],campaign_id=campaign_a.id,visitor_hash="mixed-visitor",status="confirmed",attributed_amount=Decimal("150.00"),currency="INR",is_demo=False,created_at=now,confirmed_at=now)])
        campaign_b_id=campaign_b.id;db.commit()
    first=commerce_client.get(f"/api/v1/brand/analytics/campaigns/{data['campaign_id']}",headers=data["brand"],params={"period":"lifetime"}).json()
    second=commerce_client.get(f"/api/v1/brand/analytics/campaigns/{campaign_b_id}",headers=data["brand"],params={"period":"lifetime"}).json()
    overview=commerce_client.get("/api/v1/brand/analytics/overview",headers=data["brand"],params={"period":"lifetime"}).json()
    assert first["metrics"]["confirmed_revenue"]=="100.00" and second["metrics"]["confirmed_revenue"]=="100.00"
    assert first["metrics"]["confirmed_orders"]==2 and second["metrics"]["confirmed_orders"]==1
    assert overview["metrics"]["confirmed_revenue"]=="200.00"
    filtered=commerce_client.get(f"/api/v1/brand/analytics/campaigns/{campaign_b_id}",headers=data["brand"],params={"period":"lifetime","product_id":data["product_id"]})
    assert filtered.status_code==422


def test_unlisted_campaign_cannot_be_discovered_or_applied_to(commerce_db,commerce_client):
    data=seed_campaign_activity(commerce_db)
    created=commerce_client.post("/api/v1/campaigns",headers=data["brand"],json={"title":"Invite only campaign","visibility":"unlisted","starts_at":(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),"ends_at":(datetime.now(timezone.utc)+timedelta(days=5)).isoformat()})
    assert created.status_code==201,created.text
    campaign_id=created.json()["id"]
    assert commerce_client.patch(f"/api/v1/campaigns/{campaign_id}/status",headers=data["brand"],json={"status":"published"}).status_code==200
    assert commerce_client.get("/api/v1/campaigns",params={"q":"Invite only","status":"all"}).json()==[]
    assert commerce_client.get(f"/api/v1/campaigns/{campaign_id}").status_code==404
    assert commerce_client.post(f"/api/v1/campaigns/{campaign_id}/applications",headers=data["creator"],json={"message":"Please invite me"}).status_code==404


def test_public_campaign_discovery_respects_start_and_end_windows(commerce_db,commerce_client):
    data=seed_campaign_activity(commerce_db)
    with commerce_db() as db:
        campaign=db.get(Campaign,data["campaign_id"])
        campaign.starts_at=datetime.now(timezone.utc)+timedelta(days=2)
        db.commit()
    assert commerce_client.get("/api/v1/campaigns",params={"q":"Measured Campaign"}).json()==[]
    assert commerce_client.get(f"/api/v1/campaigns/{data['campaign_id']}").status_code==404
    with commerce_db() as db:
        campaign=db.get(Campaign,data["campaign_id"])
        campaign.starts_at=datetime.now(timezone.utc)-timedelta(days=3)
        campaign.ends_at=datetime.now(timezone.utc)-timedelta(days=1)
        db.commit()
    assert commerce_client.get("/api/v1/campaigns",params={"q":"Measured Campaign"}).json()==[]
    assert commerce_client.get(f"/api/v1/campaigns/{data['campaign_id']}").status_code==404
