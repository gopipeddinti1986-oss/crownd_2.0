from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
import re, secrets
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from sqlalchemy.orm import Session
from sqlalchemy import select, func, delete, update, or_, and_
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.entities import *
from app.api.v1.auth import limiter
from app.services.referrals import campaign_is_active, eligible_product_ids, generate_referral_code, referral_eligibility, record_referral_click, visitor_hash
from app.services.conversions import flag_risk
from app.security import current_user, require_role
from app.core.config import settings
from app.services.rewards import calculate_reward
from app.api.v1.auth import router as auth_router
from app.api.v1.commerce import router as commerce_router
from app.api.v1.rewards import router as rewards_router
from app.schemas.commerce import CampaignCreate, CampaignProductsUpdate, ProductCreate, ReferralLinkCreate, ReferralLinkUpdate, ReferralRiskReview

router = APIRouter()
router.include_router(auth_router)
router.include_router(commerce_router)
router.include_router(rewards_router)
def slugify(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") + "-" + secrets.token_hex(3)
def money(n): return Decimal(str(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
def audit(db, actor, action, kind, entity):
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, entity_type=kind, entity_id=str(entity)))

@router.get("/health")
def health(): return {"status":"ok", "service":"crownd-api"}

@router.get("/creators")
def creators(q:str|None=None,niche:str|None=None,platform:str|None=None,limit:int=Query(30,ge=1,le=100),offset:int=0,db:Session=Depends(get_db),user:User=Depends(current_user)):
    stmt=select(CreatorProfile,User).join(User,User.id==CreatorProfile.user_id).where(User.is_active==True)
    if q: stmt=stmt.where((CreatorProfile.username.ilike(f"%{q}%"))|(User.name.ilike(f"%{q}%"))|(CreatorProfile.niche.ilike(f"%{q}%")))
    if niche: stmt=stmt.where(CreatorProfile.niche.ilike(f"%{niche}%"))
    if platform: stmt=stmt.where(CreatorProfile.platform.ilike(platform))
    profiles=db.execute(stmt.offset(offset).limit(limit)).all()
    return [{"user_id":u.id,"name":u.name,"username":p.username,"niche":p.niche,"location":p.location,"platform":p.platform,"followers":p.followers,"engagement":p.engagement,"crown_score":p.crown_score,"trust_score":p.trust_score,"availability":p.availability} for p,u in profiles]
@router.put("/creators/me")
def update_creator(body:dict,db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    p=db.scalar(select(CreatorProfile).where(CreatorProfile.user_id==user.id))
    for k in ("username","niche","location","bio","platform","followers","engagement","availability"):
        if k in body: setattr(p,k,body[k])
    if "name" in body: user.name=body["name"]
    db.commit(); return {"ok":True}

@router.get("/campaigns")
def campaigns(q:str|None=None,status:str="published",limit:int=30,offset:int=0,db:Session=Depends(get_db)):
    stmt=select(Campaign,BrandProfile,User).join(BrandProfile,BrandProfile.user_id==Campaign.brand_id).join(User,User.id==Campaign.brand_id)
    if status!="all": stmt=stmt.where(Campaign.status==status)
    if q: stmt=stmt.where((Campaign.title.ilike(f"%{q}%"))|(Campaign.category.ilike(f"%{q}%"))|(Campaign.description.ilike(f"%{q}%")))
    rows=db.execute(stmt.order_by(Campaign.created_at.desc()).offset(offset).limit(min(limit,100))).all()
    return [{"id":c.id,"title":c.title,"slug":c.slug,"description":c.description,"category":c.category,"platforms":c.platforms,"reward_model":c.reward_model,"reward_rate":float(c.reward_rate),"budget":float(c.budget),"status":c.status,"brand":b.name,"brand_id":c.brand_id,"product_id":c.product_id,"created_at":c.created_at.isoformat()} for c,b,u in rows]
@router.post("/campaigns",status_code=201)
def create_campaign(body:CampaignCreate,db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    requested=set(body.product_ids)
    if body.product_id is not None:
        requested.add(body.product_id)
    products=db.scalars(select(Product).where(Product.id.in_(requested),Product.brand_id==user.id,Product.status=="active")).all() if requested else []
    if len(products)!=len(requested): raise HTTPException(422,"Campaign products must be active products owned by your brand")
    c=Campaign(brand_id=user.id,product_id=body.product_id,title=body.title,slug=slugify(body.title),description=body.description,category=body.category,platforms=body.platforms,reward_model=body.reward_model,reward_rate=body.reward_rate,budget=body.budget,status="draft",starts_at=body.starts_at,ends_at=body.ends_at)
    db.add(c); db.flush()
    for product in products: db.add(CampaignProduct(campaign_id=c.id,product_id=product.id))
    audit(db,user,"campaign.created","campaign",c.id); db.commit(); return {"id":c.id,"status":c.status,"slug":c.slug,"product_ids":sorted(requested)}

@router.put("/campaigns/{campaign_id}/products")
def update_campaign_products(campaign_id:int,body:CampaignProductsUpdate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    campaign=db.get(Campaign,campaign_id)
    if not campaign: raise HTTPException(404,"Campaign not found")
    if user.role!="admin" and (user.role!="brand" or campaign.brand_id!=user.id): raise HTTPException(404,"Campaign not found")
    if campaign.status=="published" and user.role!="admin": raise HTTPException(409,"Pause the campaign before changing its eligible products")
    products=db.scalars(select(Product).where(Product.id.in_(body.product_ids),Product.brand_id==campaign.brand_id,Product.status=="active")).all()
    if len(products)!=len(body.product_ids): raise HTTPException(422,"Campaign products must be active products owned by the campaign brand")
    db.execute(delete(CampaignProduct).where(CampaignProduct.campaign_id==campaign.id))
    for product in products: db.add(CampaignProduct(campaign_id=campaign.id,product_id=product.id))
    audit(db,user,"campaign.products_updated","campaign",campaign.id); db.commit()
    return {"campaign_id":campaign.id,"product_ids":sorted(body.product_ids)}
@router.get("/campaigns/{campaign_id}")
def campaign_detail(campaign_id:int,db:Session=Depends(get_db)):
    c=db.get(Campaign,campaign_id)
    if not c: raise HTTPException(404,"Campaign not found")
    return {"id":c.id,"title":c.title,"description":c.description,"brand_id":c.brand_id,"product_id":c.product_id,"category":c.category,"reward_model":c.reward_model,"reward_rate":float(c.reward_rate),"budget":float(c.budget),"status":c.status}
@router.patch("/campaigns/{campaign_id}/status")
def change_campaign(campaign_id:int,body:dict,db:Session=Depends(get_db),user:User=Depends(current_user)):
    c=db.get(Campaign,campaign_id)
    if not c: raise HTTPException(404,"Campaign not found")
    if user.role!="admin" and (user.role!="brand" or c.brand_id!=user.id): raise HTTPException(403,"Not your campaign")
    target=body.get("status"); allowed={"draft":{"published"},"published":{"paused","completed","cancelled"},"paused":{"published","cancelled"}}
    if user.role!="admin" and target not in allowed.get(c.status,set()): raise HTTPException(409,"Invalid campaign status transition")
    if target not in {"draft","published","paused","completed","cancelled","rejected"}: raise HTTPException(422,"Unsupported status")
    c.status=target; audit(db,user,"campaign.status_changed","campaign",c.id); db.commit(); return {"id":c.id,"status":c.status}

@router.post("/campaigns/{campaign_id}/applications",status_code=201)
def apply(campaign_id:int,body:dict,db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    c=db.get(Campaign,campaign_id)
    if not c or not campaign_is_active(c): raise HTTPException(404,"Campaign is not accepting applications")
    existing=db.scalar(select(Application).where(Application.campaign_id==campaign_id,Application.creator_id==user.id))
    if existing: raise HTTPException(409,"You have already applied to this campaign")
    a=Application(campaign_id=campaign_id,creator_id=user.id,message=body.get("message","")); db.add(a); db.commit(); db.refresh(a); return {"id":a.id,"status":a.status}
@router.get("/applications")
def applications(db:Session=Depends(get_db),user:User=Depends(current_user)):
    stmt=select(Application,Campaign,User).join(Campaign,Campaign.id==Application.campaign_id).join(User,User.id==Application.creator_id)
    if user.role=="creator": stmt=stmt.where(Application.creator_id==user.id)
    elif user.role=="brand": stmt=stmt.where(Campaign.brand_id==user.id)
    elif user.role!="admin": raise HTTPException(403,"Forbidden")
    return [{"id":a.id,"campaign_id":c.id,"campaign":c.title,"creator_id":u.id,"creator":u.name,"message":a.message,"status":a.status,"created_at":a.created_at.isoformat()} for a,c,u in db.execute(stmt.order_by(Application.created_at.desc())).all()]
@router.patch("/applications/{application_id}")
def review_application(application_id:int,body:dict,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=db.get(Application,application_id)
    if not a: raise HTTPException(404,"Application not found")
    c=db.get(Campaign,a.campaign_id)
    if user.role!="admin" and (user.role!="brand" or c.brand_id!=user.id): raise HTTPException(403,"Forbidden")
    status=body.get("status")
    if status not in ("shortlisted","accepted","rejected"): raise HTTPException(422,"Invalid application status")
    a.status=status
    if status=="accepted" and campaign_is_active(c) and not db.scalar(select(Referral.id).where(Referral.campaign_id==c.id,Referral.creator_id==a.creator_id)):
        db.add(Referral(campaign_id=c.id,creator_id=a.creator_id,code=generate_referral_code(db),active=True))
    if status!="accepted":
        db.execute(update(Referral).where(Referral.campaign_id==c.id,Referral.creator_id==a.creator_id).values(active=False))
    audit(db,user,f"application.{status}","application",a.id); db.commit(); return {"id":a.id,"status":status}

@router.post("/products",status_code=201)
def create_product(body:ProductCreate,db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    if body.sale_price is not None and body.sale_price >= body.price:
        raise HTTPException(422,"Sale price must be below regular price")
    p=Product(brand_id=user.id,name=body.name,slug=slugify(body.name),description=body.description,category=body.category,price=money(body.price),sale_price=money(body.sale_price) if body.sale_price is not None else None,stock=body.stock,image_url=body.image_url,image_urls=body.image_urls,specifications=body.specifications)
    db.add(p); db.commit(); db.refresh(p); return {"id":p.id,"slug":p.slug}

@router.get("/referrals/eligible-campaigns")
def eligible_referral_campaigns(db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    stmt=select(Campaign).join(Application,Application.campaign_id==Campaign.id).where(Application.creator_id==user.id,Application.status=="accepted",Campaign.status=="published").order_by(Campaign.created_at.desc())
    rows=db.scalars(stmt).all()
    return [{"id":campaign.id,"title":campaign.title,"product_ids":eligible_product_ids(db,campaign),"ends_at":campaign.ends_at.isoformat() if campaign.ends_at else None} for campaign in rows if campaign_is_active(campaign)]


@router.get("/brand/referral-campaigns")
def brand_referral_campaigns(db:Session=Depends(get_db),user:User=Depends(require_role("brand","admin"))):
    stmt=select(Campaign)
    if user.role=="brand": stmt=stmt.where(Campaign.brand_id==user.id)
    return [{"id":campaign.id,"title":campaign.title,"status":campaign.status,"product_ids":eligible_product_ids(db,campaign)} for campaign in db.scalars(stmt.order_by(Campaign.created_at.desc())).all()]


def _referral_link_counts(db:Session,referral_ids:list[int]):
    if not referral_ids: return {}
    rows=db.execute(select(Click.referral_id,func.count(Click.id),func.count(func.distinct(func.nullif(Click.session_hash,"")))).where(Click.referral_id.in_(referral_ids),Click.status=="valid").group_by(Click.referral_id)).all()
    return {referral_id:(clicks,unique) for referral_id,clicks,unique in rows}


def _referral_link_payload(ref:Referral,campaign:Campaign,*,clicks:int|None=None,unique_visitors:int|None=None,conversion_counts:dict|None=None):
    destination_product=ref.product_id or campaign.product_id
    destination=f"/products/{destination_product}" if destination_product else f"/shop?campaign_id={campaign.id}"
    result={"id":ref.id,"campaign_id":campaign.id,"campaign":campaign.title,"creator_id":ref.creator_id,"product_id":ref.product_id,"code":ref.code,"active":ref.active,"created_at":ref.created_at.isoformat(),"url":f"/r/{ref.code}","destination":destination}
    if clicks is not None: result["clicks"]=clicks
    if unique_visitors is not None: result["unique_visitors"]=unique_visitors
    if conversion_counts is not None: result["conversions"]=conversion_counts
    return result


@router.get("/referrals/me")
def my_referrals(db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    rows=db.execute(select(Referral,Campaign).join(Campaign,Campaign.id==Referral.campaign_id).where(Referral.creator_id==user.id).order_by(Referral.created_at.desc())).all()
    counts=_referral_link_counts(db,[ref.id for ref,_campaign in rows])
    return [_referral_link_payload(ref,campaign,clicks=counts.get(ref.id,(0,0))[0],unique_visitors=counts.get(ref.id,(0,0))[1]) for ref,campaign in rows]


@router.post("/referrals/links",status_code=201)
def create_referral_link(body:ReferralLinkCreate,db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    campaign=db.get(Campaign,body.campaign_id)
    if not campaign or not campaign_is_active(campaign): raise HTTPException(409,"Campaign is not currently eligible for referral links")
    application=db.scalar(select(Application).where(Application.campaign_id==campaign.id,Application.creator_id==user.id))
    if not application or application.status!="accepted": raise HTTPException(403,"An approved campaign application is required")
    allowed=set(eligible_product_ids(db,campaign))
    product_id=body.product_id
    if product_id is not None:
        product=db.get(Product,product_id)
        if product_id not in allowed or not product or product.brand_id!=campaign.brand_id or product.status!="active": raise HTTPException(422,"Product is not eligible for this campaign")
    elif not allowed:
        raise HTTPException(409,"Campaign has no eligible products")
    existing=db.scalar(select(Referral).where(Referral.creator_id==user.id,Referral.campaign_id==campaign.id,Referral.product_id==product_id,Referral.active.is_(True)).order_by(Referral.created_at.asc()))
    if existing:
        return _referral_link_payload(existing,campaign)
    for _ in range(5):
        ref=Referral(campaign_id=campaign.id,creator_id=user.id,product_id=product_id,code=generate_referral_code(db),active=True)
        db.add(ref)
        try:
            db.flush()
            db.add(AuditLog(actor_id=user.id,action="referral.link_created",entity_type="referral",entity_id=str(ref.id)))
            db.commit(); db.refresh(ref)
            return _referral_link_payload(ref,campaign)
        except IntegrityError:
            db.rollback()
    raise HTTPException(409,"Could not allocate a unique referral code; please retry")


@router.get("/referrals/links")
def creator_referral_links(db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    rows=db.execute(select(Referral,Campaign).join(Campaign,Campaign.id==Referral.campaign_id).where(Referral.creator_id==user.id).order_by(Referral.created_at.desc())).all()
    counts=_referral_link_counts(db,[ref.id for ref,_campaign in rows])
    return {"items":[_referral_link_payload(ref,campaign,clicks=counts.get(ref.id,(0,0))[0],unique_visitors=counts.get(ref.id,(0,0))[1]) for ref,campaign in rows]}


@router.get("/referrals/links/{referral_id}")
def get_creator_referral_link(referral_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    pair=db.execute(select(Referral,Campaign).join(Campaign,Campaign.id==Referral.campaign_id).where(Referral.id==referral_id,Referral.creator_id==user.id)).first()
    if not pair: raise HTTPException(404,"Referral link not found")
    ref,campaign=pair
    counts={status:(db.scalar(select(func.count(Conversion.id)).where(Conversion.referral_id==ref.id,Conversion.status==status)) or 0) for status in ("pending","confirmed","cancelled","reversed","ineligible")}
    clicks=db.scalar(select(func.count(Click.id)).where(Click.referral_id==ref.id,Click.status=="valid")) or 0
    unique=db.scalar(select(func.count(func.distinct(Click.session_hash))).where(Click.referral_id==ref.id,Click.session_hash!="",Click.status=="valid")) or 0
    result=_referral_link_payload(ref,campaign,clicks=clicks,unique_visitors=unique,conversion_counts=counts)
    result.update({"product_views":db.scalar(select(func.count(ReferralActivity.id)).where(ReferralActivity.referral_id==ref.id,ReferralActivity.event_type=="product_view")) or 0,"cart_additions":db.scalar(select(func.count(ReferralActivity.id)).where(ReferralActivity.referral_id==ref.id,ReferralActivity.event_type=="cart_add")) or 0})
    return result


@router.patch("/referrals/links/{referral_id}")
def update_creator_referral_link(referral_id:int,body:ReferralLinkUpdate,db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    ref=db.scalar(select(Referral).where(Referral.id==referral_id,Referral.creator_id==user.id).with_for_update())
    if not ref: raise HTTPException(404,"Referral link not found")
    campaign=db.get(Campaign,ref.campaign_id)
    if body.active:
        eligible,_reason=referral_eligibility(db,ref)
        if not eligible: raise HTTPException(409,"This link cannot be reactivated because campaign eligibility is not valid")
    ref.active=body.active
    db.add(AuditLog(actor_id=user.id,action="referral.link_activated" if body.active else "referral.link_deactivated",entity_type="referral",entity_id=str(ref.id)))
    db.commit()
    return _referral_link_payload(ref,campaign)


@router.get("/r/{code}")
@limiter.limit("60/minute")
def track_referral(code:str,request:Request,response:Response,db:Session=Depends(get_db)):
    ref=db.scalar(select(Referral).where(func.lower(Referral.code)==code.lower()))
    if not ref: raise HTTPException(404,"Referral code not found")
    campaign=db.get(Campaign,ref.campaign_id)
    eligible,reason=referral_eligibility(db,ref)
    if not eligible:
        db.add(Click(referral_id=ref.id,session_hash=visitor_hash(request) or "",destination="/shop",status="ineligible"))
        risk_code={"ineligible_campaign":"INELIGIBLE_CAMPAIGN","inactive_link":"INVALID_ATTRIBUTION","unapproved_participation":"INELIGIBLE_CAMPAIGN","inactive_creator":"INVALID_ATTRIBUTION","inactive_brand":"INELIGIBLE_CAMPAIGN","no_eligible_products":"INELIGIBLE_CAMPAIGN"}.get(reason,"INVALID_ATTRIBUTION")
        flag_risk(db,risk_code,referral_id=ref.id,visitor_hash=visitor_hash(request),details=f"Referral click rejected: {reason}.")
        db.commit()
        raise HTTPException(410,"Referral is no longer eligible")
    product_id=ref.product_id or campaign.product_id
    destination=f"/products/{product_id}" if product_id else f"/shop?campaign_id={campaign.id}"
    hashed=record_referral_click(db,request,response,ref,destination)
    hour_ago=datetime.now(timezone.utc)-timedelta(hours=1)
    recent=db.scalar(select(func.count(Click.id)).where(Click.session_hash==hashed,Click.clicked_at>=hour_ago,Click.status=="valid")) or 0
    if recent>=40: flag_risk(db,"SUSPICIOUS_CLICK_VOLUME",referral_id=ref.id,visitor_hash=hashed,details="At least forty clicks from one anonymous visitor token within one hour.")
    db.commit()
    return {"ok":True,"campaign_id":campaign.id,"product_id":product_id,"destination":destination,"attribution_window_days":settings.attribution_days,"attribution_model":"last_valid_referral"}

def _conversion_payload(conversion:Conversion,order:Order):
    return {"id":conversion.id,"order_id":order.public_id,"referral_id":conversion.referral_id,"campaign_id":conversion.campaign_id,"creator_id":conversion.creator_id,"status":conversion.status,"attributed_amount":str(conversion.attributed_amount),"currency":conversion.currency,"is_demo":conversion.is_demo,"payment_method":order.payment_method,"payment_status":order.payment_status,"reason":conversion.reason,"created_at":conversion.created_at.isoformat(),"confirmed_at":conversion.confirmed_at.isoformat() if conversion.confirmed_at else None}


def _referral_metrics(db:Session,referral_ids:list[int],conversions,cutoff:datetime,product_id:int|None=None):
    if not referral_ids:
        return {"clicks":0,"unique_visitors":0,"product_views":0,"cart_additions":0,"orders":0,"confirmed_conversions":0,"pending_conversions":0,"cancelled_conversions":0,"reversed_conversions":0,"demo_conversions":0,"cod_conversions":0,"conversion_rate":0.0}
    clicks=db.scalar(select(func.count(Click.id)).where(Click.referral_id.in_(referral_ids),Click.status=="valid",Click.clicked_at>=cutoff)) or 0
    unique=db.scalar(select(func.count(func.distinct(func.nullif(Click.session_hash,"")))).where(Click.referral_id.in_(referral_ids),Click.status=="valid",Click.clicked_at>=cutoff)) or 0
    views_stmt=select(func.count(ReferralActivity.id)).where(ReferralActivity.referral_id.in_(referral_ids),ReferralActivity.event_type=="product_view",ReferralActivity.created_at>=cutoff)
    cart_stmt=select(func.count(ReferralActivity.id)).where(ReferralActivity.referral_id.in_(referral_ids),ReferralActivity.event_type=="cart_add",ReferralActivity.created_at>=cutoff)
    if product_id is not None:
        views_stmt=views_stmt.where(ReferralActivity.product_id==product_id)
        cart_stmt=cart_stmt.where(ReferralActivity.product_id==product_id)
    views=db.scalar(views_stmt) or 0
    cart_adds=db.scalar(cart_stmt) or 0
    rows=db.execute(conversions).all()
    statuses=[conversion.status for conversion,_order in rows]
    confirmed=sum(1 for status in statuses if status=="confirmed")
    return {"clicks":clicks,"unique_visitors":unique,"product_views":views,"cart_additions":cart_adds,"orders":sum(1 for status in statuses if status!="ineligible"),"confirmed_conversions":confirmed,"pending_conversions":sum(1 for status in statuses if status=="pending"),"cancelled_conversions":sum(1 for status in statuses if status=="cancelled"),"reversed_conversions":sum(1 for status in statuses if status=="reversed"),"demo_conversions":sum(1 for conversion,_order in rows if conversion.is_demo and conversion.status=="confirmed"),"cod_conversions":sum(1 for conversion,order in rows if order.payment_method=="cod" and conversion.status=="confirmed"),"conversion_rate":round(confirmed*100/unique,2) if unique else 0.0}


@router.get("/creator/referral-analytics")
def creator_referral_analytics(days:int=Query(default=30,ge=1,le=365),campaign_id:int|None=Query(default=None,gt=0),product_id:int|None=Query(default=None,gt=0),referral_id:int|None=Query(default=None,gt=0),db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    refs=db.scalars(select(Referral).where(Referral.creator_id==user.id)).all()
    if campaign_id is not None: refs=[ref for ref in refs if ref.campaign_id==campaign_id]
    if product_id is not None: refs=[ref for ref in refs if (ref.product_id in (None,product_id) and product_id in eligible_product_ids(db,db.get(Campaign,ref.campaign_id)))]
    if referral_id is not None:
        if not any(ref.id==referral_id for ref in refs): raise HTTPException(404,"Referral link not found")
        refs=[ref for ref in refs if ref.id==referral_id]
    referral_ids=[ref.id for ref in refs]
    cutoff=datetime.now(timezone.utc)-timedelta(days=days)
    stmt=select(Conversion,Order).join(Order,Order.id==Conversion.order_id).where(Conversion.creator_id==user.id,Conversion.created_at>=cutoff)
    if campaign_id is not None: stmt=stmt.where(Conversion.campaign_id==campaign_id)
    if referral_id is not None: stmt=stmt.where(Conversion.referral_id==referral_id)
    if product_id is not None:
        matching_item=select(OrderItem.id).where(OrderItem.order_id==Order.id,OrderItem.product_id==product_id,OrderItem.referral_id==Conversion.referral_id).exists()
        stmt=stmt.where(matching_item)
    return {"window_days":days,"metrics":_referral_metrics(db,referral_ids,stmt,cutoff)}


@router.get("/creator/conversions")
def creator_conversions(page:int=Query(default=1,ge=1),page_size:int=Query(default=25,ge=1,le=100),status:str|None=None,campaign_id:int|None=Query(default=None,gt=0),product_id:int|None=Query(default=None,gt=0),referral_id:int|None=Query(default=None,gt=0),db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    stmt=select(Conversion,Order).join(Order,Order.id==Conversion.order_id).where(Conversion.creator_id==user.id)
    if status: stmt=stmt.where(Conversion.status==status)
    if campaign_id: stmt=stmt.where(Conversion.campaign_id==campaign_id)
    if referral_id:
        if not db.scalar(select(Referral.id).where(Referral.id==referral_id,Referral.creator_id==user.id)): raise HTTPException(404,"Referral link not found")
        stmt=stmt.where(Conversion.referral_id==referral_id)
    if product_id:
        matching_item=select(OrderItem.id).where(OrderItem.order_id==Order.id,OrderItem.product_id==product_id,OrderItem.referral_id==Conversion.referral_id).exists()
        stmt=stmt.where(matching_item)
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.execute(stmt.order_by(Conversion.created_at.desc(),Conversion.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[_conversion_payload(conversion,order) for conversion,order in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size}


@router.get("/brand/campaign-analytics/{campaign_id}")
def brand_campaign_analytics(campaign_id:int,days:int=Query(default=30,ge=1,le=365),product_id:int|None=Query(default=None,gt=0),db:Session=Depends(get_db),user:User=Depends(require_role("brand","admin"))):
    campaign=db.get(Campaign,campaign_id)
    if not campaign or (user.role=="brand" and campaign.brand_id!=user.id): raise HTTPException(404,"Campaign not found")
    refs=db.scalars(select(Referral).where(Referral.campaign_id==campaign.id)).all()
    if product_id is not None and product_id not in eligible_product_ids(db,campaign): raise HTTPException(422,"Product is not eligible for this campaign")
    if product_id is not None: refs=[ref for ref in refs if ref.product_id in (None,product_id)]
    referral_ids=[ref.id for ref in refs]
    cutoff=datetime.now(timezone.utc)-timedelta(days=days)
    stmt=select(Conversion,Order).join(Order,Order.id==Conversion.order_id).where(Conversion.campaign_id==campaign.id,Conversion.created_at>=cutoff)
    if product_id is not None:
        matching_item=select(OrderItem.id).where(OrderItem.order_id==Order.id,OrderItem.product_id==product_id,OrderItem.referral_id==Conversion.referral_id).exists()
        stmt=stmt.where(matching_item)
    rows=db.execute(stmt).all()
    metrics=_referral_metrics(db,referral_ids,stmt,cutoff,product_id=product_id)
    creator_rows=db.execute(select(User.id,User.name).join(Referral,Referral.creator_id==User.id).where(Referral.campaign_id==campaign.id).group_by(User.id,User.name)).all()
    creator_clicks=db.execute(select(Referral.creator_id,func.count(Click.id),func.count(func.distinct(func.nullif(Click.session_hash,"")))).join(Referral,Referral.id==Click.referral_id).where(Referral.campaign_id==campaign.id,Click.status=="valid",Click.clicked_at>=cutoff).group_by(Referral.creator_id)).all()
    creator_activities=db.execute(select(Referral.creator_id,ReferralActivity.event_type,func.count(ReferralActivity.id)).join(Referral,Referral.id==ReferralActivity.referral_id).where(Referral.campaign_id==campaign.id,ReferralActivity.created_at>=cutoff,*( [ReferralActivity.product_id==product_id] if product_id is not None else [])).group_by(Referral.creator_id,ReferralActivity.event_type)).all()
    creator_conversions=db.execute(select(Conversion.creator_id,Conversion.status,func.count(Conversion.id)).where(Conversion.campaign_id==campaign.id,Conversion.created_at>=cutoff).group_by(Conversion.creator_id,Conversion.status)).all()
    if product_id is not None:
        matching_item=select(OrderItem.id).where(OrderItem.order_id==Conversion.order_id,OrderItem.product_id==product_id,OrderItem.referral_id==Conversion.referral_id).exists()
        matching_creator_conversions=db.execute(select(Conversion.creator_id,Conversion.status,func.count(Conversion.id)).where(Conversion.campaign_id==campaign.id,Conversion.created_at>=cutoff,matching_item).group_by(Conversion.creator_id,Conversion.status)).all()
        creator_conversions=matching_creator_conversions
    click_map={creator_id:(count,unique) for creator_id,count,unique in creator_clicks}
    activity_map={}
    for creator_id,event_type,count in creator_activities: activity_map.setdefault(creator_id,{})[event_type]=count
    conversion_map={}
    for creator_id,status,count in creator_conversions: conversion_map.setdefault(creator_id,{})[status]=count
    creator_performance=[]
    for creator_id,name in creator_rows:
        clicks,unique=click_map.get(creator_id,(0,0)); activities=activity_map.get(creator_id,{}); counts=conversion_map.get(creator_id,{})
        confirmed=counts.get("confirmed",0)
        creator_performance.append({"creator_id":creator_id,"creator_name":name,"clicks":clicks,"unique_visitors":unique,"product_views":activities.get("product_view",0),"cart_additions":activities.get("cart_add",0),"orders":sum(counts.values()),"conversions":confirmed,"pending_conversions":counts.get("pending",0),"conversion_rate":round(confirmed*100/unique,2) if unique else 0.0})
    creator_performance.sort(key=lambda item:(item["conversions"],item["conversion_rate"],item["clicks"]),reverse=True)
    product_stmt=select(OrderItem.product_id,OrderItem.product_name,func.count(func.distinct(Conversion.id))).join(Conversion,Conversion.order_id==OrderItem.order_id).where(Conversion.campaign_id==campaign.id,Conversion.status=="confirmed",OrderItem.referral_id==Conversion.referral_id,OrderItem.product_id.is_not(None))
    if product_id is not None: product_stmt=product_stmt.where(OrderItem.product_id==product_id)
    products=db.execute(product_stmt.group_by(OrderItem.product_id,OrderItem.product_name).order_by(func.count(func.distinct(Conversion.id)).desc())).all()
    return {"campaign_id":campaign.id,"window_days":days,"product_id":product_id,"metrics":metrics,"creator_performance":creator_performance,"product_performance":[{"product_id":id,"product_name":name,"conversions":count} for id,name,count in products]}


@router.get("/admin/referrals")
def admin_referrals(q:str|None=Query(default=None,max_length=100),creator_id:int|None=Query(default=None,gt=0),campaign_id:int|None=Query(default=None,gt=0),product_id:int|None=Query(default=None,gt=0),active:bool|None=None,page:int=Query(default=1,ge=1),page_size:int=Query(default=25,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    stmt=select(Referral,Campaign).join(Campaign,Campaign.id==Referral.campaign_id)
    if q: stmt=stmt.where(Referral.code.ilike(f"%{q.strip()}%"))
    if creator_id: stmt=stmt.where(Referral.creator_id==creator_id)
    if campaign_id: stmt=stmt.where(Referral.campaign_id==campaign_id)
    if product_id:
        has_campaign_products=select(CampaignProduct.campaign_id).where(CampaignProduct.campaign_id==Campaign.id).exists()
        has_product_link=select(CampaignProduct.campaign_id).where(CampaignProduct.campaign_id==Campaign.id,CampaignProduct.product_id==product_id).exists()
        same_brand_product=select(Product.id).where(Product.id==product_id,Product.brand_id==Campaign.brand_id,Product.status=="active").exists()
        campaign_eligibility=or_(and_(has_campaign_products,has_product_link),and_(~has_campaign_products,or_(Campaign.product_id==product_id,and_(Campaign.product_id.is_(None),same_brand_product))))
        stmt=stmt.where(or_(Referral.product_id==product_id,and_(Referral.product_id.is_(None),campaign_eligibility)))
    if active is not None: stmt=stmt.where(Referral.active.is_(active))
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.execute(stmt.order_by(Referral.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
    counts=_referral_link_counts(db,[ref.id for ref,_campaign in rows])
    return {"items":[_referral_link_payload(ref,campaign,clicks=counts.get(ref.id,(0,0))[0],unique_visitors=counts.get(ref.id,(0,0))[1]) for ref,campaign in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size}


@router.patch("/admin/referrals/links/{referral_id}")
def admin_update_referral_link(referral_id:int,body:ReferralLinkUpdate,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    ref=db.scalar(select(Referral).where(Referral.id==referral_id).with_for_update())
    if not ref: raise HTTPException(404,"Referral link not found")
    if body.active:
        eligible,_reason=referral_eligibility(db,ref)
        if not eligible: raise HTTPException(409,"This link is not eligible for reactivation")
    ref.active=body.active
    audit(db,user,"admin.referral_link_activated" if body.active else "admin.referral_link_deactivated","referral",ref.id); db.commit()
    return {"id":ref.id,"active":ref.active,"code":ref.code}


@router.get("/admin/conversions")
def admin_conversions(q:str|None=Query(default=None,max_length=100),status:str|None=None,creator_id:int|None=Query(default=None,gt=0),campaign_id:int|None=Query(default=None,gt=0),product_id:int|None=Query(default=None,gt=0),page:int=Query(default=1,ge=1),page_size:int=Query(default=25,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    stmt=select(Conversion,Order).join(Order,Order.id==Conversion.order_id)
    if status:
        if status not in {"pending","confirmed","cancelled","reversed","ineligible"}: raise HTTPException(422,"Unsupported conversion status")
        stmt=stmt.where(Conversion.status==status)
    if creator_id: stmt=stmt.where(Conversion.creator_id==creator_id)
    if campaign_id: stmt=stmt.where(Conversion.campaign_id==campaign_id)
    if product_id:
        matching_item=select(OrderItem.id).where(OrderItem.order_id==Order.id,OrderItem.product_id==product_id,OrderItem.referral_id==Conversion.referral_id).exists()
        stmt=stmt.where(matching_item)
    if q:
        term=f"%{q.strip()}%"
        stmt=stmt.outerjoin(Referral,Referral.id==Conversion.referral_id).where(or_(Order.public_id.ilike(term),Referral.code.ilike(term)))
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.execute(stmt.order_by(Conversion.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[_conversion_payload(conversion,order) for conversion,order in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size}


@router.get("/admin/referral-risk")
def admin_referral_risk(status:str="open",risk_code:str|None=None,creator_id:int|None=Query(default=None,gt=0),campaign_id:int|None=Query(default=None,gt=0),product_id:int|None=Query(default=None,gt=0),page:int=Query(default=1,ge=1),page_size:int=Query(default=25,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    if status not in {"open","reviewed","dismissed","all"}: raise HTTPException(422,"Unsupported risk status")
    stmt=select(ReferralRiskFlag)
    if status!="all": stmt=stmt.where(ReferralRiskFlag.status==status)
    if risk_code: stmt=stmt.where(ReferralRiskFlag.risk_code==risk_code)
    if creator_id is not None or campaign_id is not None or product_id is not None:
        stmt=stmt.outerjoin(Referral,Referral.id==ReferralRiskFlag.referral_id)
        if creator_id is not None: stmt=stmt.where(Referral.creator_id==creator_id)
        if campaign_id is not None: stmt=stmt.where(Referral.campaign_id==campaign_id)
        if product_id is not None:
            item_exists=select(OrderItem.id).join(Conversion,Conversion.order_id==OrderItem.order_id).where(Conversion.id==ReferralRiskFlag.conversion_id,OrderItem.product_id==product_id,OrderItem.referral_id==Conversion.referral_id).exists()
            stmt=stmt.where(or_(Referral.product_id==product_id,item_exists))
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.scalars(stmt.order_by(ReferralRiskFlag.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"items":[{"id":row.id,"risk_code":row.risk_code,"referral_id":row.referral_id,"conversion_id":row.conversion_id,"details":row.details,"status":row.status,"created_at":row.created_at.isoformat()} for row in rows],"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size}


@router.patch("/admin/referral-risk/{flag_id}")
def review_referral_risk(flag_id:int,body:ReferralRiskReview,db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    risk=db.get(ReferralRiskFlag,flag_id)
    if not risk: raise HTTPException(404,"Risk flag not found")
    risk.status=body.status; risk.reviewed_by=user.id; risk.reviewed_at=datetime.now(timezone.utc)
    audit(db,user,f"referral_risk.{body.status}","referral_risk",risk.id); db.commit()
    return {"id":risk.id,"status":risk.status,"reviewed_at":risk.reviewed_at.isoformat()}


@router.post("/orders",status_code=410)
def create_order():
    raise HTTPException(410,"Guest single-product checkout is retired. Use authenticated cart checkout and select a payment method.")
@router.get("/orders")
def list_orders(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role=="admin": rows=db.scalars(select(Order).order_by(Order.created_at.desc())).all()
    elif user.role=="brand": rows=db.scalars(select(Order).join(Product,Product.id==Order.product_id).where(Product.brand_id==user.id)).all()
    elif user.role=="creator": rows=db.scalars(select(Order).join(Referral,Referral.id==Order.referral_id).where(Referral.creator_id==user.id)).all()
    else: rows=db.scalars(select(Order).where(Order.customer_email==user.email)).all()
    return [{"id":o.public_id,"product_id":o.product_id,"quantity":o.quantity,"amount":float(o.amount),"payment_status":o.payment_status,"status":o.status,"created_at":o.created_at.isoformat()} for o in rows]

@router.get("/rewards/me")
def my_rewards(db:Session=Depends(get_db),user:User=Depends(require_role("creator"))):
    return [{"id":r.id,"order_id":db.get(Order,r.order_id).public_id,"amount":float(r.amount),"status":r.status,"eligible_at":r.eligible_at.isoformat(),"is_demo":r.is_demo,"payable":not r.is_demo and r.status=="eligible"} for r in db.scalars(select(Reward).where(Reward.creator_id==user.id).order_by(Reward.created_at.desc())).all()]
@router.post("/payouts",status_code=410)
def request_payout():
    raise HTTPException(410,"Payout processing is not available. Only administrators can record clearly disclosed payout simulations; no money is transferred.")

@router.get("/analytics/overview")
def analytics(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role=="admin":
        users=db.scalar(select(func.count(User.id))) or 0; campaigns=db.scalar(select(func.count(Campaign.id))) or 0; orders=db.scalar(select(func.count(Order.id)).where(Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))) or 0; gmv=db.scalar(select(func.coalesce(func.sum(Order.amount),0)).where(Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))) or 0
        return {"users":users,"campaigns":campaigns,"orders":orders,"gmv":float(gmv)}
    if user.role=="brand":
        campaigns=db.scalars(select(Campaign).where(Campaign.brand_id==user.id)).all(); ids=[c.id for c in campaigns]
        products=db.select if False else None
        clicks=db.scalar(select(func.coalesce(func.sum(Referral.clicks),0)).where(Referral.campaign_id.in_(ids))) if ids else 0
        orders=db.scalars(select(Order).join(Referral,Referral.id==Order.referral_id).join(Campaign,Campaign.id==Referral.campaign_id).where(Campaign.brand_id==user.id,Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))).all()
        return {"campaigns":len(campaigns),"clicks":clicks or 0,"orders":len(orders),"revenue":float(sum((o.amount for o in orders),Decimal(0))),"rewards":float(db.scalar(select(func.coalesce(func.sum(Reward.amount),0)).join(Order,Reward.order_id==Order.id).join(Referral,Referral.id==Order.referral_id).join(Campaign,Campaign.id==Referral.campaign_id).where(Campaign.brand_id==user.id,Reward.is_demo.is_(False))) or 0)}
    if user.role=="creator":
        refs=db.scalars(select(Referral).where(Referral.creator_id==user.id)).all(); ids=[r.id for r in refs]
        rewards=db.scalars(select(Reward).where(Reward.creator_id==user.id,Reward.is_demo.is_(False))).all()
        orders=db.scalar(select(func.count(Order.id)).where(Order.referral_id.in_(ids),Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))) if ids else 0
        return {"clicks":sum(r.clicks for r in refs),"orders":orders or 0,"earnings":float(sum((r.amount for r in rewards),Decimal(0))),"pending":float(sum((r.amount for r in rewards if r.status=="pending"),Decimal(0))),"eligible":float(sum((r.amount for r in rewards if r.status=="eligible"),Decimal(0))),"active_campaigns":len(refs)}
    return {"orders":db.scalar(select(func.count(Order.id)).where(Order.customer_email==user.email)) or 0}
@router.get("/ai/matches/{campaign_id}")
def matches(campaign_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("brand","admin"))):
    c=db.get(Campaign,campaign_id)
    if not c: raise HTTPException(404,"Campaign not found")
    if user.role=="brand" and c.brand_id!=user.id: raise HTTPException(403,"Forbidden")
    rows=db.execute(select(CreatorProfile,User).join(User,User.id==CreatorProfile.user_id).where(CreatorProfile.availability==True)).all()
    recs=[]
    for p,u in rows:
        niche=100 if c.category.lower() in p.niche.lower() or p.niche.lower() in c.category.lower() else 35
        engagement=min(100,int(p.engagement*10))
        platform=100 if p.platform.lower() in c.platforms.lower() else 30
        score=round(niche*.30+engagement*.20+platform*.20+min(p.crown_score/10,100)*.15+p.trust_score*.15)
        reasons=[]
        if niche>=70: reasons.append("Niche aligns with campaign category")
        if engagement>=60: reasons.append("Strong creator-reported engagement")
        if platform==100: reasons.append(f"Active on {p.platform}")
        recs.append({"user_id":u.id,"name":u.name,"username":p.username,"niche":p.niche,"platform":p.platform,"followers":p.followers,"engagement":p.engagement,"score":score,"reasons":reasons or ["Available creator; consider reviewing audience fit"]})
    return sorted(recs,key=lambda x:x["score"],reverse=True)[:30]

@router.get("/analytics/timeseries")
def analytics_timeseries(db:Session=Depends(get_db),user:User=Depends(current_user)):
    from calendar import month_abbr
    from collections import defaultdict
    if user.role=="admin": stmt=select(Order).where(Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))
    elif user.role=="brand": stmt=select(Order).join(Product,Product.id==Order.product_id).where(Product.brand_id==user.id,Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))
    elif user.role=="creator": stmt=select(Order).join(Referral,Referral.id==Order.referral_id).where(Referral.creator_id==user.id,Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))
    else: stmt=select(Order).where(Order.customer_email==user.email,Order.payment_status=="paid",Order.payment_method.in_(["cod","online"]))
    since=datetime.now(timezone.utc)-timedelta(days=210)
    monthly=defaultdict(lambda: {"revenue":Decimal(0),"orders":0})
    for order in db.scalars(stmt.where(Order.created_at>=since)).all():
        key=order.created_at.strftime("%Y-%m"); monthly[key]["revenue"]+=Decimal(order.amount); monthly[key]["orders"]+=1
    current=datetime.now(timezone.utc).replace(day=1)
    series=[]
    for i in range(6,-1,-1):
        month_index=current.year*12+current.month-1-i
        year,month=divmod(month_index,12); month+=1
        key=f"{year:04d}-{month:02d}"
        series.append({"month":month_abbr[month],"revenue":float(monthly[key]["revenue"]),"orders":monthly[key]["orders"]})
    return series

@router.get("/admin/audit-logs")
def audit_logs(db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    return [{"id":a.id,"actor_id":a.actor_id,"action":a.action,"entity_type":a.entity_type,"entity_id":a.entity_id,"created_at":a.created_at.isoformat()} for a in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()]
@router.get("/admin/users")
def admin_users(db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    return [{"id":u.id,"name":u.name,"email":u.email,"role":u.role,"active":u.is_active,"created_at":u.created_at.isoformat()} for u in db.scalars(select(User).order_by(User.created_at.desc()).limit(300)).all()]
