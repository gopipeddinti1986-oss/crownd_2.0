from datetime import timezone
import re, secrets
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.entities import Application, AuditLog, Campaign, CampaignProduct, Product, Referral, User
from app.schemas.commerce import CampaignUpdate
from app.security import current_user, require_role
from app.services.analytics import campaign_metrics_by_campaigns,date_window

router=APIRouter()


def _campaign_payload(db:Session,campaign:Campaign,*,product_ids:list[int]|None=None,products:list|None=None,creator_count:int|None=None,metrics:dict|None=None):
    if product_ids is None:
        product_ids=list(db.scalars(select(CampaignProduct.product_id).where(CampaignProduct.campaign_id==campaign.id).order_by(CampaignProduct.product_id)).all())
        if not product_ids and campaign.product_id:product_ids=[campaign.product_id]
    if products is None:
        available_ids=product_ids
        if not available_ids and campaign.product_id is None:available_ids=list(db.scalars(select(Product.id).where(Product.brand_id==campaign.brand_id,Product.status=="active")).all())
        products=db.execute(select(Product.id,Product.name,Product.category).where(Product.id.in_(available_ids))).all() if available_ids else []
    if creator_count is None:creator_count=db.scalar(select(func.count(func.distinct(Application.creator_id))).where(Application.campaign_id==campaign.id,Application.status=="accepted")) or 0
    return {"id":campaign.id,"title":campaign.title,"slug":campaign.slug,"description":campaign.description,"category":campaign.category,"platforms":campaign.platforms,"reward_model":campaign.reward_model,"reward_rate":str(campaign.reward_rate),"budget":str(campaign.budget),"status":campaign.status,"starts_at":campaign.starts_at.isoformat() if campaign.starts_at else None,"ends_at":campaign.ends_at.isoformat() if campaign.ends_at else None,"objectives":campaign.objectives or [],"target_audience":campaign.target_audience or "","creator_requirements":campaign.creator_requirements or "","visibility":campaign.visibility or "public","performance_goals":campaign.performance_goals or {},"product_ids":product_ids,"products":[({"id":row.id,"name":row.name,"category":row.category} if not isinstance(row,dict) else row) for row in products],"accepted_creator_count":creator_count,"metrics":metrics or {"clicks":0,"orders":0,"confirmed_orders":0,"confirmed_revenue":"0.00","pending_revenue":"0.00","generated_reward_value":"0.00","simulated":"0.00"},"created_at":campaign.created_at.isoformat()}


@router.get("/brand/campaigns")
def brand_campaigns(q:str|None=Query(None,max_length=120),status:str|None=Query(None,pattern="^(draft|published|paused|completed|cancelled|rejected)$"),sort:str=Query("created_at",pattern="^(created_at|title|status|starts_at|ends_at|budget)$"),direction:str=Query("desc",pattern="^(asc|desc)$"),page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    stmt=select(Campaign).where(Campaign.brand_id==user.id)
    if q:
        term=f"%{q.strip()}%"
        stmt=stmt.where(Campaign.title.ilike(term)|Campaign.description.ilike(term)|Campaign.category.ilike(term))
    if status:stmt=stmt.where(Campaign.status==status)
    column=getattr(Campaign,sort)
    stmt=stmt.order_by(column.asc() if direction=="asc" else column.desc(),Campaign.id.desc())
    total=db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows=db.scalars(stmt.offset((page-1)*page_size).limit(page_size)).all()
    ids=[campaign.id for campaign in rows]
    product_rows=db.execute(select(CampaignProduct.campaign_id,Product.id,Product.name,Product.category).join(Product,Product.id==CampaignProduct.product_id).where(CampaignProduct.campaign_id.in_(ids)).order_by(CampaignProduct.campaign_id,Product.name)).all() if ids else []
    product_map={}
    for campaign_key,product_key,name,category in product_rows:product_map.setdefault(campaign_key,[]).append({"id":product_key,"name":name,"category":category})
    counts={campaign_key:int(count) for campaign_key,count in db.execute(select(Application.campaign_id,func.count(func.distinct(Application.creator_id))).where(Application.campaign_id.in_(ids),Application.status=="accepted").group_by(Application.campaign_id)).all()} if ids else {}
    analytics=campaign_metrics_by_campaigns(db,ids,brand_id=user.id,window=date_window("last30"))
    fallback_ids=[campaign.product_id for campaign in rows if campaign.product_id and not product_map.get(campaign.id)]
    fallback_rows=db.execute(select(Product.id,Product.name,Product.category).where(Product.id.in_(fallback_ids))).all() if fallback_ids else []
    fallback_map={row.id:{"id":row.id,"name":row.name,"category":row.category} for row in fallback_rows}
    payload=[]
    for campaign in rows:
        products=product_map.get(campaign.id,[])
        if not products and campaign.product_id and campaign.product_id in fallback_map:
            products=[fallback_map[campaign.product_id]]
        payload.append(_campaign_payload(db,campaign,product_ids=[item["id"] for item in products],products=products,creator_count=counts.get(campaign.id,0),metrics=analytics[campaign.id]))
    return {"items":payload,"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size}


@router.get("/brand/campaigns/{campaign_id}")
def brand_campaign_detail(campaign_id:int,db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    campaign=db.scalar(select(Campaign).where(Campaign.id==campaign_id,Campaign.brand_id==user.id))
    if not campaign:raise HTTPException(404,"Campaign not found")
    metrics=campaign_metrics_by_campaigns(db,[campaign.id],brand_id=user.id,window=date_window("last30"))[campaign.id]
    return _campaign_payload(db,campaign,metrics=metrics)


@router.put("/campaigns/{campaign_id}")
def update_campaign(campaign_id:int,body:CampaignUpdate,db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    campaign=db.scalar(select(Campaign).where(Campaign.id==campaign_id,Campaign.brand_id==user.id))
    if not campaign:raise HTTPException(404,"Campaign not found")
    if campaign.status not in {"draft","paused"}:raise HTTPException(409,"Pause the campaign before editing its configuration")
    values=body.model_dump(exclude_unset=True)
    product_ids=values.pop("product_ids",None)
    current_products=set(db.scalars(select(CampaignProduct.product_id).where(CampaignProduct.campaign_id==campaign.id)).all())
    if not current_products and campaign.product_id:current_products.add(campaign.product_id)
    requested=set(product_ids) if product_ids is not None else set(current_products)
    if "product_id" in values:
        selected_primary=values["product_id"]
        if selected_primary is None:
            if campaign.product_id in requested:requested.discard(campaign.product_id)
        else:requested.add(selected_primary)
    if requested:
        owned=db.scalars(select(Product.id).where(Product.id.in_(requested),Product.brand_id==user.id,Product.status=="active")).all()
        if len(owned)!=len(requested):raise HTTPException(422,"Campaign products must be active products owned by your brand")
    start=values.get("starts_at",campaign.starts_at);end=values.get("ends_at",campaign.ends_at)
    if start and end:
        start=start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc)
        end=end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end.astimezone(timezone.utc)
        if end<=start:raise HTTPException(422,"Campaign end must follow its start")
    if "title" in values:
        values["slug"]=re.sub(r"[^a-z0-9]+","-",values["title"].lower()).strip("-")+"-"+secrets.token_hex(3)
    if "performance_goals" in values and values["performance_goals"] is not None:
        values["performance_goals"]={key:str(value) for key,value in values["performance_goals"].items()}
    for field,value in values.items():setattr(campaign,field,value)
    if product_ids is not None or "product_id" in values:
        selected=sorted(requested)
        db.query(CampaignProduct).filter(CampaignProduct.campaign_id==campaign.id).delete(synchronize_session=False)
        for product_id in selected:db.add(CampaignProduct(campaign_id=campaign.id,product_id=product_id))
        if "product_id" not in values:campaign.product_id=selected[0] if selected else None
    db.add(AuditLog(actor_id=user.id,action="campaign.updated",entity_type="campaign",entity_id=str(campaign.id)))
    db.commit();db.refresh(campaign)
    metrics=campaign_metrics_by_campaigns(db,[campaign.id],brand_id=user.id,window=date_window("last30"))[campaign.id]
    return _campaign_payload(db,campaign,metrics=metrics)
