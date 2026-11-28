from datetime import date, datetime, timezone
from decimal import Decimal
import csv, io
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.v1.auth import limiter
from app.database import get_db
from app.models.entities import Application, Campaign, CampaignProduct, Conversion, Order, OrderItem, Product, Referral, Reward, User
from app.security import require_role
from app.services.analytics import (DateWindow, bound_campaign_window, campaign_metrics, campaign_metrics_by_campaigns,
    campaign_overview, campaign_table, date_window)
from app.services.referrals import as_utc

router=APIRouter()
PERIOD_PATTERN="^(today|yesterday|last7|last30|last90|lifetime|custom)$"


def _window(period:str,start_date:date|None,end_date:date|None,campaign:Campaign|None=None)->DateWindow:
    try:
        value=date_window(period,start_date,end_date,campaign=campaign)
        return bound_campaign_window(campaign,value) if campaign else value
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


def _campaign_ids(db:Session,brand_id:int|None=None):
    stmt=select(Campaign.id)
    if brand_id is not None:stmt=stmt.where(Campaign.brand_id==brand_id)
    return list(db.scalars(stmt.order_by(Campaign.id)).all())


def _csv_cell(value):
    text="" if value is None else str(value)
    if text[:1] in {"\t","\r","\n"} or text.lstrip(" \t\r\n")[:1] in {"=","+","-","@"}:return "'"+text
    return text


def _csv_response(headers:list[str],rows:list[dict],filename:str):
    output=io.StringIO(newline="")
    writer=csv.writer(output,lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:writer.writerow([_csv_cell(row.get(key)) for key in headers])
    return Response(content=output.getvalue(),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":f'attachment; filename="{filename}"',"Cache-Control":"no-store"})


def _apply_table_filters(rows:list[dict],*,creator_id:int|None=None,product_id:int|None=None,q:str|None=None,sort:str,direction:str,page:int,page_size:int):
    if creator_id is not None:rows=[row for row in rows if row.get("creator_id")==creator_id]
    if product_id is not None:rows=[row for row in rows if row.get("product_id")==product_id]
    if q:
        term=q.strip().casefold()
        rows=[row for row in rows if term in str(row.get("creator",row.get("product",""))).casefold() or term in str(row.get("campaign","" )).casefold()]
    rows.sort(key=lambda row:(Decimal(str(row.get(sort) or 0)) if sort in {"confirmed_revenue","attributed_revenue","conversion_rate_pct","average_order_value","reward_value"} else int(row.get(sort) or 0),str(row.get("creator",row.get("product",""))).casefold()),reverse=direction=="desc")
    total=len(rows)
    return rows[(page-1)*page_size:page*page_size],total


@router.get("/brand/analytics/overview")
@limiter.limit("60/minute")
def brand_analytics_overview(request:Request,response:Response,period:str=Query("last30",pattern=PERIOD_PATTERN),start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    window=_window(period,start_date,end_date)
    campaigns=db.scalars(select(Campaign).where(Campaign.brand_id==user.id).order_by(Campaign.created_at.desc())).all()
    ids=[campaign.id for campaign in campaigns]
    metrics=campaign_metrics(db,brand_id=user.id,campaign_ids=ids,window=window)
    counts={status:int(value) for status,value in db.execute(select(Campaign.status,func.count(Campaign.id)).where(Campaign.brand_id==user.id).group_by(Campaign.status)).all()}
    now=datetime.now(timezone.utc)
    active_campaigns=sum(1 for campaign in campaigns if campaign.status=="published" and (as_utc(campaign.starts_at) is None or as_utc(campaign.starts_at)<=now) and (as_utc(campaign.ends_at) is None or as_utc(campaign.ends_at)>=now))
    creator_count=db.scalar(select(func.count(func.distinct(Application.creator_id))).join(Campaign,Campaign.id==Application.campaign_id).where(Campaign.brand_id==user.id,Application.status=="accepted")) or 0
    creators=campaign_table(db,dimension="creator",brand_id=user.id,campaign_ids=ids,window=window)
    converting=sum(1 for row in creators if row["confirmed_orders"]>0)
    creators.sort(key=lambda row:(Decimal(row["confirmed_revenue"]),row["confirmed_orders"],Decimal(row["conversion_rate_pct"]),Decimal(row["average_order_value"])),reverse=True)
    comparison=campaign_metrics_by_campaigns(db,ids,brand_id=user.id,window=window)
    campaign_rows=[{"campaign_id":campaign.id,"campaign":campaign.title,"status":campaign.status,"metrics":comparison[campaign.id]} for campaign in campaigns]
    campaign_rows.sort(key=lambda row:(Decimal(row["metrics"]["confirmed_revenue"]),row["metrics"]["confirmed_orders"],Decimal(row["metrics"]["click_to_confirmed_rate_pct"])),reverse=True)
    return {"window":{"period":window.label,"start":window.start.isoformat() if window.start else None,"end_exclusive":window.end.isoformat() if window.end else None,"timezone":"UTC"},"campaigns":{"total":len(campaigns),"active":active_campaigns,"completed":counts.get("completed",0),"paused":counts.get("paused",0),"draft":counts.get("draft",0),"by_status":counts},"creators":{"participating":creator_count,"generating_confirmed_conversions":converting,"top_performers":creators[:10],"ranking":"Confirmed revenue → confirmed conversions → conversion rate → average order value"},"metrics":metrics,"campaign_comparison":campaign_rows}


@router.get("/brand/analytics/campaigns/{campaign_id}")
@limiter.limit("60/minute")
def brand_campaign_intelligence(campaign_id:int,request:Request,response:Response,period:str=Query("last30",pattern=PERIOD_PATTERN),start_date:date|None=None,end_date:date|None=None,product_id:int|None=Query(None,gt=0),db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    campaign=db.scalar(select(Campaign).where(Campaign.id==campaign_id,Campaign.brand_id==user.id))
    if not campaign:raise HTTPException(404,"Campaign not found")
    if product_id is not None:
        configured=set(db.scalars(select(CampaignProduct.product_id).where(CampaignProduct.campaign_id==campaign.id)).all())
        if campaign.product_id:configured.add(campaign.product_id)
        if not configured and campaign.product_id is None:
            configured=set(db.scalars(select(Product.id).where(Product.brand_id==user.id)).all())
        historically_attributed=db.scalar(select(OrderItem.id).join(Referral,Referral.id==OrderItem.referral_id).where(
            OrderItem.product_id==product_id,Referral.campaign_id==campaign.id).limit(1))
        if product_id not in configured and not historically_attributed:
            raise HTTPException(422,"Product is not associated with this campaign")
    window=_window(period,start_date,end_date,campaign)
    return campaign_overview(db,campaign,window,product_id)


@router.get("/brand/analytics/creators")
@limiter.limit("60/minute")
def brand_creator_performance(request:Request,response:Response,period:str=Query("last30",pattern=PERIOD_PATTERN),start_date:date|None=None,end_date:date|None=None,campaign_id:int|None=Query(None,gt=0),creator_id:int|None=Query(None,gt=0),q:str|None=Query(None,max_length=120),sort:str=Query("confirmed_revenue",pattern="^(confirmed_revenue|confirmed_orders|conversion_rate_pct|clicks|reward_value|average_order_value)$"),direction:str=Query("desc",pattern="^(asc|desc)$"),page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    campaign_ids=_campaign_ids(db,user.id)
    if campaign_id is not None:
        if campaign_id not in campaign_ids:raise HTTPException(404,"Campaign not found")
        campaign_ids=[campaign_id]
    window=_window(period,start_date,end_date)
    rows=campaign_table(db,dimension="creator",brand_id=user.id,campaign_ids=campaign_ids,window=window)
    rows,total=_apply_table_filters(rows,creator_id=creator_id,q=q,sort=sort,direction=direction,page=page,page_size=page_size)
    return {"items":rows,"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size,"ranking_criterion":"confirmed_revenue → confirmed_orders → conversion_rate_pct → average_order_value","window":{"period":window.label,"start":window.start.isoformat() if window.start else None,"end_exclusive":window.end.isoformat() if window.end else None}}


@router.get("/brand/analytics/products")
@limiter.limit("60/minute")
def brand_product_performance(request:Request,response:Response,period:str=Query("last30",pattern=PERIOD_PATTERN),start_date:date|None=None,end_date:date|None=None,campaign_id:int|None=Query(None,gt=0),product_id:int|None=Query(None,gt=0),q:str|None=Query(None,max_length=120),sort:str=Query("confirmed_revenue",pattern="^(confirmed_revenue|confirmed_orders|conversion_rate_pct|clicks|reward_value|average_order_value)$"),direction:str=Query("desc",pattern="^(asc|desc)$"),page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    ids=_campaign_ids(db,user.id)
    if campaign_id is not None:
        if campaign_id not in ids:raise HTTPException(404,"Campaign not found")
        ids=[campaign_id]
    window=_window(period,start_date,end_date)
    rows=campaign_table(db,dimension="product",brand_id=user.id,campaign_ids=ids,window=window)
    rows,total=_apply_table_filters(rows,product_id=product_id,q=q,sort=sort,direction=direction,page=page,page_size=page_size)
    return {"items":rows,"total":total,"page":page,"page_size":page_size,"pages":(total+page_size-1)//page_size,"window":{"period":window.label,"start":window.start.isoformat() if window.start else None,"end_exclusive":window.end.isoformat() if window.end else None}}


@router.get("/brand/analytics/export")
@limiter.limit("10/minute")
def brand_analytics_export(request:Request,response:Response,kind:str=Query(...,pattern="^(campaigns|creators|products|conversions|rewards)$"),period:str=Query("last30",pattern=PERIOD_PATTERN),start_date:date|None=None,end_date:date|None=None,campaign_id:int|None=Query(None,gt=0),product_id:int|None=Query(None,gt=0),db:Session=Depends(get_db),user:User=Depends(require_role("brand"))):
    ids=_campaign_ids(db,user.id)
    if campaign_id is not None:
        if campaign_id not in ids:raise HTTPException(404,"Campaign not found")
        ids=[campaign_id]
    window=_window(period,start_date,end_date)
    if kind=="campaigns":
        metrics=campaign_metrics_by_campaigns(db,ids,brand_id=user.id,window=window);campaigns=db.scalars(select(Campaign).where(Campaign.id.in_(ids)).order_by(Campaign.id)).all() if ids else []
        rows=[{"campaign":c.title,"status":c.status,**metrics[c.id]} for c in campaigns]
        headers=["campaign","status","clicks","unique_visitors","orders","confirmed_orders","confirmed_revenue","pending_revenue","cancelled_revenue","reversed_revenue","pending","pending_collection","under_review","eligible","approved","reversed","rejected","generated_reward_value","simulated"]
    elif kind in {"creators","products"}:
        dimension="creator" if kind=="creators" else "product"
        rows=campaign_table(db,dimension=dimension,brand_id=user.id,campaign_ids=ids,product_id=product_id,window=window)
        rows.sort(key=lambda item:(Decimal(item["confirmed_revenue"]),item["confirmed_orders"]),reverse=True)
        headers=( ["campaign","creator","clicks","unique_visitors","orders","confirmed_orders","conversion_rate_pct","confirmed_revenue","pending_revenue","average_order_value","reward_records","reward_value","pending_rewards","pending_collection_rewards","under_review_rewards","eligible_rewards","approved_rewards","rejected_rewards","simulated_rewards","reversed_rewards"] if dimension=="creator" else ["campaign","product","category","clicks","unique_visitors","orders","confirmed_orders","conversion_rate_pct","confirmed_revenue","pending_revenue","average_order_value","reward_records","reward_value","pending_rewards","pending_collection_rewards","under_review_rewards","eligible_rewards","approved_rewards","rejected_rewards","simulated_rewards","reversed_rewards"] )
    elif kind=="rewards":
        stmt=select(Reward.id,Reward.campaign_id,Reward.creator_id,Reward.product_id,Reward.amount,Reward.status,Reward.is_demo,Reward.created_at,Reward.currency).where(Reward.campaign_id.in_(ids) if ids else False)
        if product_id is not None:stmt=stmt.where(Reward.product_id==product_id)
        if window.start:stmt=stmt.where(Reward.created_at>=window.start)
        if window.end:stmt=stmt.where(Reward.created_at<window.end)
        rows=[{"reward_id":r.id,"campaign_id":r.campaign_id,"creator_id":r.creator_id,"product_id":r.product_id,"amount":str(r.amount),"status":r.status,"is_demo":"yes" if r.is_demo else "no","created_at":r.created_at.isoformat(),"currency":r.currency,"actual_transfer":"no"} for r in db.execute(stmt.order_by(Reward.created_at.desc()).limit(5000)).all()]
        headers=["reward_id","campaign_id","creator_id","product_id","amount","status","is_demo","created_at","currency","actual_transfer"]
    else:
        stmt=select(Conversion.id,Order.public_id,Conversion.campaign_id,Conversion.creator_id,Conversion.status,Conversion.attributed_amount,Conversion.currency,Conversion.is_demo,Order.payment_method,Order.payment_status,Conversion.created_at).join(Order,Order.id==Conversion.order_id).where(Conversion.campaign_id.in_(ids) if ids else False)
        if window.start:stmt=stmt.where(Conversion.created_at>=window.start)
        if window.end:stmt=stmt.where(Conversion.created_at<window.end)
        if product_id is not None:stmt=stmt.where(select(OrderItem.id).where(OrderItem.order_id==Order.id,OrderItem.product_id==product_id).exists())
        rows=[{"conversion_id":r.id,"order_reference":r.public_id,"campaign_id":r.campaign_id,"creator_id":r.creator_id,"status":r.status,"attributed_amount":str(r.attributed_amount),"currency":r.currency,"is_demo":"yes" if r.is_demo else "no","payment_method":r.payment_method,"payment_status":r.payment_status,"created_at":r.created_at.isoformat()} for r in db.execute(stmt.order_by(Conversion.created_at.desc()).limit(5000)).all()]
        headers=["conversion_id","order_reference","campaign_id","creator_id","status","attributed_amount","currency","is_demo","payment_method","payment_status","created_at"]
    return _csv_response(headers,rows,f"crownd-{kind}-analytics.csv")


@router.get("/admin/analytics/overview")
@limiter.limit("30/minute")
def admin_analytics_overview(request:Request,response:Response,period:str=Query("last30",pattern=PERIOD_PATTERN),start_date:date|None=None,end_date:date|None=None,brand_id:int|None=Query(None,gt=0),campaign_id:int|None=Query(None,gt=0),creator_id:int|None=Query(None,gt=0),product_id:int|None=Query(None,gt=0),db:Session=Depends(get_db),user:User=Depends(require_role("admin"))):
    window=_window(period,start_date,end_date)
    if campaign_id is not None:
        campaign=db.get(Campaign,campaign_id)
        if not campaign:raise HTTPException(404,"Campaign not found")
        if brand_id is not None and campaign.brand_id!=brand_id:raise HTTPException(422,"Campaign does not belong to the selected brand")
        ids=[campaign_id];brand_id=campaign.brand_id
    else:ids=_campaign_ids(db,brand_id)
    metrics=campaign_metrics(db,brand_id=brand_id,campaign_ids=ids,creator_id=creator_id,product_id=product_id,window=window)
    campaign_count=db.scalar(select(func.count(Campaign.id)).where(Campaign.id.in_(ids) if ids else False)) or 0
    status_counts={status:int(count) for status,count in db.execute(select(Campaign.status,func.count(Campaign.id)).where(Campaign.id.in_(ids) if ids else False).group_by(Campaign.status)).all()}
    total_creators=db.scalar(select(func.count(User.id)).where(User.role=="creator")) or 0
    creator_rows=campaign_table(db,dimension="creator",brand_id=brand_id,campaign_ids=ids,window=window)
    active_creator_ids={row["creator_id"] for row in creator_rows if row["confirmed_orders"]>0 and row["creator_id"] is not None}
    campaign_rows=db.scalars(select(Campaign).where(Campaign.id.in_(ids) if ids else False).order_by(Campaign.id)).all()
    campaign_metric_map=campaign_metrics_by_campaigns(db,ids,brand_id=brand_id,window=window,creator_id=creator_id,product_id=product_id)
    comparison=[{"campaign_id":campaign.id,"campaign":campaign.title,"status":campaign.status,"metrics":campaign_metric_map[campaign.id]} for campaign in campaign_rows]
    comparison.sort(key=lambda row:(Decimal(row["metrics"]["confirmed_revenue"]),row["metrics"]["confirmed_orders"]),reverse=True)
    return {"scope":"platform" if brand_id is None else "brand","brand_id":brand_id,"campaign_id":campaign_id,"campaigns":{"total":campaign_count,"by_status":status_counts,"comparison":comparison[:50]},"creators":{"total_platform_creators":total_creators,"generating_confirmed_conversions":len(active_creator_ids)},"metrics":metrics,"filters":{"creator_id":creator_id,"product_id":product_id,"period":window.label},"customer_data_excluded":True}
