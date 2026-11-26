"""Database-derived campaign intelligence using line attribution and payment states."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import and_, case, distinct, func, or_, select
from sqlalchemy.orm import Session
from app.models.entities import (Application, Campaign, CampaignProduct, Click, Conversion,
    Order, OrderItem, Product, Referral, ReferralActivity, Reward, User)

ZERO=Decimal("0.00")
CENT=Decimal("0.01")
UTC=timezone.utc

@dataclass(frozen=True)
class DateWindow:
    start: datetime | None
    end: datetime | None
    label: str


def utc_day_start(value:date)->datetime:
    return datetime.combine(value,time.min,tzinfo=UTC)


def date_window(period:str="last30",start_date:date|None=None,end_date:date|None=None,*,campaign:Campaign|None=None,now:datetime|None=None)->DateWindow:
    now=(now or datetime.now(UTC)).astimezone(UTC)
    today=now.date()
    if period=="custom":
        if start_date is None or end_date is None:raise ValueError("Custom range requires both start_date and end_date")
        if end_date<start_date:raise ValueError("end_date must be on or after start_date")
        if (end_date-start_date).days>3660:raise ValueError("Custom date range cannot exceed ten years; use campaign lifetime instead")
        return DateWindow(utc_day_start(start_date),utc_day_start(end_date+timedelta(days=1)),"custom")
    if start_date is not None or end_date is not None:raise ValueError("start_date and end_date are only valid with period=custom")
    if period=="today":return DateWindow(utc_day_start(today),now,period)
    if period=="yesterday":return DateWindow(utc_day_start(today-timedelta(days=1)),utc_day_start(today),period)
    if period in {"last7","last30","last90"}:
        days=int(period[4:])
        return DateWindow(utc_day_start(today-timedelta(days=days-1)),now,period)
    if period=="lifetime":
        if campaign:
            campaign_start=campaign.starts_at or campaign.created_at
            if campaign_start.tzinfo is None:campaign_start=campaign_start.replace(tzinfo=UTC)
            start=utc_day_start(campaign_start.astimezone(UTC).date())
            campaign_end=campaign.ends_at
            if campaign_end and campaign_end.tzinfo is None:campaign_end=campaign_end.replace(tzinfo=UTC)
            effective_end=min(campaign_end.astimezone(UTC),now) if campaign_end else now
            end=utc_day_start(effective_end.date()+timedelta(days=1))
            return DateWindow(start,end,"lifetime")
        return DateWindow(None,now,"lifetime")
    raise ValueError("Unsupported period")


def bound_campaign_window(campaign:Campaign,window:DateWindow)->DateWindow:
    start=window.start
    end=window.end
    campaign_start=campaign.starts_at
    campaign_end=campaign.ends_at
    if campaign_start and campaign_start.tzinfo is None:campaign_start=campaign_start.replace(tzinfo=UTC)
    if campaign_end and campaign_end.tzinfo is None:campaign_end=campaign_end.replace(tzinfo=UTC)
    if campaign_start and (start is None or campaign_start>start):start=campaign_start
    if campaign_end:
        exclusive=campaign_end+timedelta(microseconds=1)
        if end is None or exclusive<end:end=exclusive
    return DateWindow(start,end,window.label)


def _apply_window(stmt,column,window:DateWindow):
    if window.start is not None:stmt=stmt.where(column>=window.start)
    if window.end is not None:stmt=stmt.where(column<window.end)
    return stmt


def _confirmed():
    return and_(Conversion.status=="confirmed",Order.payment_status=="paid",Order.payment_method!="demo",Conversion.is_demo.is_(False))


def _simulated():
    return and_(Conversion.status=="confirmed",Conversion.is_demo.is_(True),Order.payment_method=="demo")


def _pending():
    return and_(Conversion.status=="pending",Order.payment_status.in_(["pending","unpaid"]))


def _reversed():
    return or_(Conversion.status=="reversed",Order.payment_status.in_(["refunded","partially_refunded"]))


def _cancelled():
    return and_(or_(Conversion.status=="cancelled",Order.status=="cancelled"),~_reversed())


def attributed_lines(db:Session,*,brand_id:int|None=None,campaign_id:int|None=None,campaign_ids:list[int]|None=None,creator_id:int|None=None,product_id:int|None=None,window:DateWindow|None=None):
    stmt=select(OrderItem,Order,Referral,Campaign,Conversion,Product).join(Order,Order.id==OrderItem.order_id).join(Referral,Referral.id==OrderItem.referral_id).join(Campaign,Campaign.id==Referral.campaign_id).outerjoin(Conversion,Conversion.order_id==Order.id).outerjoin(Product,Product.id==OrderItem.product_id)
    stmt=stmt.where(Conversion.id.is_not(None),Conversion.status!="ineligible")
    if brand_id is not None:stmt=stmt.where(Campaign.brand_id==brand_id)
    if campaign_id is not None:stmt=stmt.where(Campaign.id==campaign_id)
    if campaign_ids is not None:stmt=stmt.where(Campaign.id.in_(campaign_ids) if campaign_ids else False)
    if creator_id is not None:stmt=stmt.where(Referral.creator_id==creator_id)
    if product_id is not None:stmt=stmt.where(OrderItem.product_id==product_id)
    if window:stmt=_apply_window(stmt,Order.created_at,window)
    return stmt


def line_aggregates(db:Session,*,group_by=(),brand_id:int|None=None,campaign_id:int|None=None,campaign_ids:list[int]|None=None,creator_id:int|None=None,product_id:int|None=None,window:DateWindow|None=None):
    stmt=attributed_lines(db,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window)
    order_id=Order.id
    metrics=[
        func.count(distinct(case((_pending(),order_id)))).label("pending_orders"),
        func.count(distinct(case((_confirmed(),order_id)))).label("confirmed_orders"),
        func.count(distinct(case((_simulated(),order_id)))).label("simulated_orders"),
        func.count(distinct(case((_cancelled(),order_id)))).label("cancelled_orders"),
        func.count(distinct(case((_reversed(),order_id)))).label("reversed_orders"),
        func.count(distinct(order_id)).label("orders"),
        func.count(distinct(case((Order.payment_method=="cod",order_id)))).label("cod_orders"),
        func.count(distinct(case((Order.payment_method=="demo",order_id)))).label("demo_orders"),
        func.sum(OrderItem.line_total).label("gross_attributed_order_value"),
        func.sum(case((_confirmed(),OrderItem.line_total),else_=0)).label("confirmed_revenue"),
        func.sum(case((_pending(),OrderItem.line_total),else_=0)).label("pending_revenue"),
        func.sum(case((_simulated(),OrderItem.line_total),else_=0)).label("simulated_revenue"),
        func.sum(case((_cancelled(),OrderItem.line_total),else_=0)).label("cancelled_revenue"),
        func.sum(case((_reversed(),OrderItem.line_total),else_=0)).label("reversed_revenue"),
    ]
    stmt=stmt.with_only_columns(*group_by,*metrics).group_by(*group_by)
    return db.execute(stmt).all()


def click_aggregates(db:Session,*,brand_id:int|None=None,campaign_id:int|None=None,campaign_ids:list[int]|None=None,creator_id:int|None=None,product_id:int|None=None,window:DateWindow|None=None,group_by=()):
    stmt=select(*group_by,func.count(Click.id).label("clicks"),func.count(distinct(func.nullif(Click.session_hash,""))).label("unique_visitors")).join(Referral,Referral.id==Click.referral_id).join(Campaign,Campaign.id==Referral.campaign_id).where(Click.status=="valid")
    if brand_id is not None:stmt=stmt.where(Campaign.brand_id==brand_id)
    if campaign_id is not None:stmt=stmt.where(Campaign.id==campaign_id)
    if campaign_ids is not None:stmt=stmt.where(Campaign.id.in_(campaign_ids) if campaign_ids else False)
    if creator_id is not None:stmt=stmt.where(Referral.creator_id==creator_id)
    if product_id is not None:stmt=stmt.where(Referral.product_id==product_id)
    if window:stmt=_apply_window(stmt,Click.clicked_at,window)
    return db.execute(stmt.group_by(*group_by)).all()


def activity_aggregates(db:Session,*,brand_id:int|None=None,campaign_id:int|None=None,campaign_ids:list[int]|None=None,creator_id:int|None=None,product_id:int|None=None,window:DateWindow|None=None,group_by=()):
    stmt=select(*group_by,ReferralActivity.event_type,func.count(ReferralActivity.id)).join(Referral,Referral.id==ReferralActivity.referral_id).join(Campaign,Campaign.id==Referral.campaign_id)
    if brand_id is not None:stmt=stmt.where(Campaign.brand_id==brand_id)
    if campaign_id is not None:stmt=stmt.where(Campaign.id==campaign_id)
    if campaign_ids is not None:stmt=stmt.where(Campaign.id.in_(campaign_ids) if campaign_ids else False)
    if creator_id is not None:stmt=stmt.where(Referral.creator_id==creator_id)
    if product_id is not None:stmt=stmt.where(ReferralActivity.product_id==product_id)
    if window:stmt=_apply_window(stmt,ReferralActivity.created_at,window)
    stmt=stmt.group_by(*group_by,ReferralActivity.event_type)
    return db.execute(stmt).all()


def reward_aggregates(db:Session,*,brand_id:int|None=None,campaign_id:int|None=None,campaign_ids:list[int]|None=None,creator_id:int|None=None,product_id:int|None=None,window:DateWindow|None=None,group_by=()):
    stmt=select(*group_by,Reward.status,Reward.is_demo,func.count(Reward.id),func.coalesce(func.sum(Reward.amount),0)).select_from(Reward)
    if brand_id is not None:stmt=stmt.where(Reward.campaign_id.in_(select(Campaign.id).where(Campaign.brand_id==brand_id)))
    if campaign_id is not None:stmt=stmt.where(Reward.campaign_id==campaign_id)
    if campaign_ids is not None:stmt=stmt.where(Reward.campaign_id.in_(campaign_ids) if campaign_ids else False)
    if creator_id is not None:stmt=stmt.where(Reward.creator_id==creator_id)
    if product_id is not None:stmt=stmt.where(Reward.product_id==product_id)
    if window:stmt=_apply_window(stmt,Reward.created_at,window)
    stmt=stmt.group_by(*group_by,Reward.status,Reward.is_demo)
    return db.execute(stmt).all()


def _money(value)->str:
    return str(Decimal(value or 0).quantize(CENT,rounding=ROUND_HALF_UP))


def _empty_metrics():
    return {"orders":0,"pending_orders":0,"confirmed_orders":0,"cancelled_orders":0,"reversed_orders":0,"simulated_orders":0,"cod_orders":0,"demo_orders":0,"gross_attributed_order_value":"0.00","attributed_revenue":"0.00","confirmed_revenue":"0.00","pending_revenue":"0.00","cancelled_revenue":"0.00","reversed_revenue":"0.00","simulated_revenue":"0.00","clicks":0,"unique_visitors":0,"product_views":0,"cart_additions":0,"click_to_order_rate_pct":"0.00","click_to_confirmed_rate_pct":"0.00","conversion_rate_pct":"0.00","visitor_to_order_rate_pct":"0.00","cancellation_rate_pct":"0.00","reversal_rate_pct":"0.00","average_order_value":"0.00","revenue_per_click":"0.00"}


def _rate(numerator:int,denominator:int)->str:
    return _money(Decimal(numerator)*100/denominator) if denominator else "0.00"


def _attach_reward_metrics(db:Session,metrics:dict,*,brand_id:int|None=None,campaign_id:int|None=None,campaign_ids:list[int]|None=None,creator_id:int|None=None,product_id:int|None=None,window:DateWindow|None=None):
    rows=reward_aggregates(db,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window)
    reward={"pending":"0.00","pending_collection":"0.00","under_review":"0.00","eligible":"0.00","approved":"0.00","reversed":"0.00","rejected":"0.00","simulated":"0.00","generated_reward_value":"0.00","reward_records":0}
    buckets={key:Decimal(0) for key in reward if key not in {"reward_records"}}
    for status,is_demo,count,amount in rows:
        amount=Decimal(amount or 0);reward["reward_records"]+=count
        if is_demo:buckets["simulated"]+=amount
        elif status in buckets:buckets[status]+=amount
        if not is_demo and status not in {"reversed","rejected"}:buckets["generated_reward_value"]+=amount
    for key,value in buckets.items():reward[key]=_money(value)
    metrics.update(reward)
    return metrics


def _finish_metrics(raw,clicks:int=0,visitors:int=0,views:int=0,cart_adds:int=0):
    metrics=_empty_metrics()
    if raw:
        values=raw._mapping
        metrics.update({key:int(values[key] or 0) for key in ("orders","pending_orders","confirmed_orders","cancelled_orders","reversed_orders","simulated_orders","cod_orders","demo_orders")})
        for key in ("gross_attributed_order_value","confirmed_revenue","pending_revenue","cancelled_revenue","reversed_revenue","simulated_revenue"):
            metrics[key]=_money(values[key])
        metrics["attributed_revenue"]=_money(Decimal(metrics["confirmed_revenue"])+Decimal(metrics["pending_revenue"]))
    metrics.update({"clicks":clicks,"unique_visitors":visitors,"product_views":views,"cart_additions":cart_adds})
    metrics["click_to_order_rate_pct"]=_rate(metrics["orders"],clicks)
    metrics["click_to_confirmed_rate_pct"]=_rate(metrics["confirmed_orders"],clicks)
    metrics["conversion_rate_pct"]=_rate(metrics["confirmed_orders"],visitors)
    metrics["visitor_to_order_rate_pct"]=_rate(metrics["orders"],visitors)
    metrics["cancellation_rate_pct"]=_rate(metrics["cancelled_orders"],metrics["orders"])
    metrics["reversal_rate_pct"]=_rate(metrics["reversed_orders"],metrics["orders"])
    metrics["average_order_value"]=_money(Decimal(metrics["confirmed_revenue"])/metrics["confirmed_orders"] if metrics["confirmed_orders"] else 0)
    metrics["revenue_per_click"]=_money(Decimal(metrics["confirmed_revenue"])/clicks if clicks else 0)
    return metrics


def campaign_metrics(db:Session,*,brand_id:int|None=None,campaign_id:int|None=None,campaign_ids:list[int]|None=None,creator_id:int|None=None,product_id:int|None=None,window:DateWindow|None=None):
    row_list=line_aggregates(db,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window)
    raw=row_list[0] if row_list else None
    clicks=click_aggregates(db,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window)
    click_count=int(clicks[0].clicks or 0) if clicks else 0;visitors=int(clicks[0].unique_visitors or 0) if clicks else 0
    activities=activity_aggregates(db,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window)
    counts={event:int(count) for event,count in activities}
    metrics=_finish_metrics(raw,click_count,visitors,counts.get("product_view",0),counts.get("cart_add",0))
    return _attach_reward_metrics(db,metrics,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window)


def campaign_metrics_by_campaigns(db:Session,campaign_ids:list[int],*,brand_id:int,window:DateWindow,creator_id:int|None=None,product_id:int|None=None):
    if not campaign_ids:return {}
    raw=line_aggregates(db,group_by=(Campaign.id,),brand_id=brand_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window)
    clicks=click_aggregates(db,brand_id=brand_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window,group_by=(Campaign.id,))
    activities=activity_aggregates(db,brand_id=brand_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window,group_by=(Campaign.id,))
    rewards=reward_aggregates(db,brand_id=brand_id,campaign_ids=campaign_ids,creator_id=creator_id,product_id=product_id,window=window,group_by=(Reward.campaign_id,))
    raw_map={int(row[0]):row for row in raw};click_map={int(row[0]):(int(row.clicks or 0),int(row.unique_visitors or 0)) for row in clicks}
    activity_map={}
    for cid,event_type,count in activities:activity_map.setdefault(int(cid),{})[event_type]=int(count)
    reward_map={}
    for cid,status,demo,count,amount in rewards:
        bucket=reward_map.setdefault(int(cid),{"pending":"0.00","pending_collection":"0.00","under_review":"0.00","eligible":"0.00","approved":"0.00","reversed":"0.00","rejected":"0.00","simulated":"0.00","generated_reward_value":"0.00","reward_records":0})
        bucket["reward_records"]+=int(count);amount=Decimal(amount or 0)
        if demo:bucket["simulated"]=_money(Decimal(bucket["simulated"])+amount)
        else:
            if status in {"pending","pending_collection","under_review","eligible","approved","reversed","rejected"}:bucket[status]=_money(Decimal(bucket[status])+amount)
            if status not in {"reversed","rejected"}:bucket["generated_reward_value"]=_money(Decimal(bucket["generated_reward_value"])+amount)
    result={}
    for cid in campaign_ids:
        clicks_count,visitors=click_map.get(cid,(0,0));acts=activity_map.get(cid,{})
        metrics=_finish_metrics(raw_map.get(cid),clicks_count,visitors,acts.get("product_view",0),acts.get("cart_add",0))
        default={"pending":"0.00","pending_collection":"0.00","under_review":"0.00","eligible":"0.00","approved":"0.00","reversed":"0.00","rejected":"0.00","simulated":"0.00","generated_reward_value":"0.00","reward_records":0}
        metrics.update(reward_map.get(cid,default));result[cid]=metrics
    return result


def campaign_table(db:Session,*,dimension:str,brand_id:int|None=None,campaign_id:int|None=None,campaign_ids:list[int]|None=None,window:DateWindow|None=None,product_id:int|None=None):
    campaign_stmt=select(Campaign.id,Campaign.brand_id,Campaign.product_id).order_by(Campaign.id)
    if brand_id is not None:campaign_stmt=campaign_stmt.where(Campaign.brand_id==brand_id)
    if campaign_id is not None:campaign_stmt=campaign_stmt.where(Campaign.id==campaign_id)
    if campaign_ids is not None:campaign_stmt=campaign_stmt.where(Campaign.id.in_(campaign_ids) if campaign_ids else False)
    campaign_rows=db.execute(campaign_stmt).all();campaign_map={int(row.id):row for row in campaign_rows}
    if dimension=="creator":
        groups=(Campaign.id,Referral.creator_id);click_group=(Campaign.id,Referral.creator_id);activity_group=(Campaign.id,Referral.creator_id);reward_group=(Reward.campaign_id,Reward.creator_id);id_label="creator_id"
        seed_rows=db.execute(select(Application.campaign_id,Application.creator_id).join(Campaign,Campaign.id==Application.campaign_id).where(Application.status=="accepted",Application.creator_id.is_not(None),Campaign.id.in_(campaign_map) if campaign_map else False)).all()
        name_rows=db.execute(select(User.id,User.name).where(User.id.in_({int(row.creator_id) for row in seed_rows}))).all() if seed_rows else []
        names={int(row.id):row.name for row in name_rows}
    elif dimension=="product":
        groups=(Campaign.id,OrderItem.product_id,OrderItem.product_name,Product.category);click_group=(Campaign.id,Referral.product_id);activity_group=(Campaign.id,ReferralActivity.product_id);reward_group=(Reward.campaign_id,Reward.product_id);id_label="product_id"
        names={}
        for cid,campaign in campaign_map.items():
            associated=db.execute(select(Product.id,Product.name,Product.category).join(CampaignProduct,CampaignProduct.product_id==Product.id).where(CampaignProduct.campaign_id==cid,Product.brand_id==campaign.brand_id,Product.status=="active")).all()
            if not associated and campaign.product_id:
                associated=db.execute(select(Product.id,Product.name,Product.category).where(Product.id==campaign.product_id,Product.brand_id==campaign.brand_id)).all()
            if not associated and not campaign.product_id:
                associated=db.execute(select(Product.id,Product.name,Product.category).where(Product.brand_id==campaign.brand_id,Product.status=="active")).all()
            for item in associated:names[(cid,int(item.id))]=(item.name,item.category)
    else:raise ValueError("unknown table dimension")
    raw_rows=line_aggregates(db,group_by=groups,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=list(campaign_map),product_id=product_id,window=window)
    raw_map={(int(row[0]),int(row[1]) if row[1] is not None else -1):row for row in raw_rows}
    click_rows=click_aggregates(db,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=list(campaign_map),product_id=product_id,window=window,group_by=click_group)
    click_map={(int(row[0]),int(row[1])):(int(row.clicks or 0),int(row.unique_visitors or 0)) for row in click_rows if row[0] is not None and row[1] is not None}
    activity_rows=activity_aggregates(db,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=list(campaign_map),product_id=product_id,window=window,group_by=activity_group)
    activity_map={}
    for cid,dim,event_type,count in activity_rows:
        if cid is not None and dim is not None:activity_map.setdefault((int(cid),int(dim)),{})[event_type]=int(count)
    reward_rows=reward_aggregates(db,brand_id=brand_id,campaign_id=campaign_id,campaign_ids=list(campaign_map),product_id=product_id,window=window,group_by=reward_group)
    reward_map={}
    for cid,dim,status,demo,count,amount in reward_rows:
        if cid is None or dim is None:continue
        key=(int(cid),int(dim));entry=reward_map.setdefault(key,{"reward_records":0,"reward_value":Decimal(0),"pending_rewards":Decimal(0),"pending_collection_rewards":Decimal(0),"under_review_rewards":Decimal(0),"eligible_rewards":Decimal(0),"approved_rewards":Decimal(0),"simulated_rewards":Decimal(0),"reversed_rewards":Decimal(0),"rejected_rewards":Decimal(0)})
        entry["reward_records"]+=count;amount=Decimal(amount or 0)
        if demo:entry["simulated_rewards"]+=amount
        elif status not in {"reversed","rejected"}:entry["reward_value"]+=amount
        if not demo and status=="pending":entry["pending_rewards"]+=amount
        if not demo and status=="under_review":entry["under_review_rewards"]+=amount
        if not demo and status=="pending_collection":entry["pending_collection_rewards"]+=amount
        if not demo and status=="eligible":entry["eligible_rewards"]+=amount
        if not demo and status=="approved":entry["approved_rewards"]+=amount
        if not demo and status=="reversed":entry["reversed_rewards"]+=amount
        if not demo and status=="rejected":entry["rejected_rewards"]+=amount
    seeds={(int(row.campaign_id),int(row.creator_id)) for row in seed_rows} if dimension=="creator" else set(names)
    keys=seeds|set(raw_map)|set(click_map)|set(activity_map)|set(reward_map)
    title_rows=db.execute(select(Campaign.id,Campaign.title).where(Campaign.id.in_([cid for cid,_ in keys]))).all() if keys else []
    titles={int(row.id):row.title for row in title_rows}
    results=[]
    for key in sorted(keys,key=lambda value:(value[0],value[1])):
        cid,dim=key;raw=raw_map.get(key);clicks,visitors=click_map.get(key,(0,0));acts=activity_map.get(key,{})
        metrics=_finish_metrics(raw,clicks,visitors,acts.get("product_view",0),acts.get("cart_add",0))
        reward=reward_map.get(key,{"reward_records":0,"reward_value":ZERO,"pending_rewards":ZERO,"pending_collection_rewards":ZERO,"under_review_rewards":ZERO,"eligible_rewards":ZERO,"approved_rewards":ZERO,"simulated_rewards":ZERO,"reversed_rewards":ZERO,"rejected_rewards":ZERO})
        entry={"campaign_id":cid,"campaign":titles.get(cid,"Former campaign"),id_label:(None if dim==-1 else dim)}
        if dimension=="creator":entry["creator"]=names.get(dim,"Former creator")
        else:entry.update({"product":names.get((cid,dim),(raw[2] if raw else "Former product",raw[3] if raw else None))[0],"category":names.get((cid,dim),(raw[2] if raw else "Former product",raw[3] if raw else None))[1]})
        entry.update(metrics)
        entry.update({field:(int(value) if field=="reward_records" else _money(value)) for field,value in reward.items()})
        results.append(entry)
    return results


def campaign_overview(db:Session,campaign:Campaign,window:DateWindow,product_id:int|None=None):
    metrics=campaign_metrics(db,brand_id=campaign.brand_id,campaign_id=campaign.id,product_id=product_id,window=window)
    accepted=db.scalar(select(func.count(func.distinct(Application.creator_id))).where(Application.campaign_id==campaign.id,Application.status=="accepted")) or 0
    roi={"available":False,"reason":"No actual campaign cost records exist. Campaign budget is a ceiling, not recorded spend.","revenue_to_cost_ratio":None,"roi_pct":None,"cost_per_conversion":None}
    expense=Decimal(metrics["generated_reward_value"])
    reward_efficiency={"available":expense>0,"ratio":_money(Decimal(metrics["confirmed_revenue"])/expense) if expense else None,"definition":"Confirmed attributed revenue divided by generated non-demo reward value (excluding reversed/rejected records)."}
    metrics["reward_efficiency"]=reward_efficiency
    metrics["roi"]=roi
    metrics["revenue_per_creator"]=_money(Decimal(metrics["confirmed_revenue"])/accepted if accepted else 0)
    product_ids=list(db.scalars(select(CampaignProduct.product_id).where(CampaignProduct.campaign_id==campaign.id)).all())
    if not product_ids and campaign.product_id:product_ids=[campaign.product_id]
    if not product_ids and campaign.product_id is None:product_ids=list(db.scalars(select(Product.id).where(Product.brand_id==campaign.brand_id,Product.status=="active")).all())
    if product_id is not None:product_ids=[product_id]
    products=db.execute(select(Product.id,Product.name).where(Product.id.in_(product_ids))).all() if product_ids else []
    creators=campaign_table(db,dimension="creator",brand_id=campaign.brand_id,campaign_id=campaign.id,window=window,product_id=product_id)
    product_rows=campaign_table(db,dimension="product",brand_id=campaign.brand_id,campaign_id=campaign.id,window=window,product_id=product_id)
    active_creators=sum(1 for creator in creators if creator["confirmed_orders"]>0)
    return {"campaign":{"id":campaign.id,"name":campaign.title,"status":campaign.status,"starts_at":campaign.starts_at.isoformat() if campaign.starts_at else None,"ends_at":campaign.ends_at.isoformat() if campaign.ends_at else None,"objectives":campaign.objectives or [],"target_audience":campaign.target_audience or "","creator_requirements":campaign.creator_requirements or "","budget_ceiling":_money(campaign.budget or 0),"creator_count":accepted,"active_creators":active_creators,"products":[{"id":r.id,"name":r.name} for r in products]},"product_filter":product_id,"window":{"period":window.label,"start":window.start.isoformat() if window.start else None,"end_exclusive":window.end.isoformat() if window.end else None},"metrics":metrics,"creators":creators,"products":product_rows,"trends":campaign_trends(db,campaign,window,product_id),"funnel":[{"stage":"Referral clicks","count":metrics["clicks"]},{"stage":"Unique visitors","count":metrics["unique_visitors"]},{"stage":"Product views","count":metrics["product_views"]},{"stage":"Cart additions","count":metrics["cart_additions"]},{"stage":"Orders","count":metrics["orders"]},{"stage":"Confirmed conversions","count":metrics["confirmed_orders"]}],"insights":rule_based_insights(metrics,creators,product_rows)}


def campaign_trends(db:Session,campaign:Campaign,window:DateWindow,product_id:int|None=None):
    # Aggregate line revenue and order conversions at UTC-day granularity. Keep event and sales denominators separate.
    day=func.date(Order.created_at)
    stmt=attributed_lines(db,brand_id=campaign.brand_id,campaign_id=campaign.id,product_id=product_id,window=window).with_only_columns(day.label("day"),func.count(distinct(case((_confirmed(),Order.id)))).label("confirmed_orders"),func.sum(case((_confirmed(),OrderItem.line_total),else_=0)).label("confirmed_revenue")).group_by(day).order_by(day)
    sales={str(d):(int(orders or 0),_money(amount)) for d,orders,amount in db.execute(stmt).all()}
    click_stmt=select(func.date(Click.clicked_at).label("day"),func.count(Click.id)).join(Referral,Referral.id==Click.referral_id).where(Referral.campaign_id==campaign.id,Click.status=="valid")
    if product_id is not None:click_stmt=click_stmt.where(Referral.product_id==product_id)
    click_stmt=_apply_window(click_stmt,Click.clicked_at,window)
    click_map={str(d):int(count) for d,count in db.execute(click_stmt.group_by(func.date(Click.clicked_at))).all()}
    if window.start is None or window.end is None:return [{"date":d,"confirmed_orders":v[0],"confirmed_revenue":v[1],"clicks":click_map.get(d,0)} for d,v in sorted(sales.items())]
    start=window.start.date();end=(window.end-timedelta(microseconds=1)).date();span=(end-start).days
    step=max(1,(span+1)//90)
    result=[]
    for offset in range(0,span+1,step):
        current=start+timedelta(days=offset);key=current.isoformat()
        # Grouping buckets daily for 90 or fewer days; for longer windows aggregate each stride.
        days=[(start+timedelta(days=i)).isoformat() for i in range(offset,min(offset+step,span+1))]
        count=sum(sales.get(item,(0,"0.00"))[0] for item in days)
        revenue=sum((Decimal(sales.get(item,(0,"0.00"))[1]) for item in days),ZERO)
        clicks=sum(click_map.get(item,0) for item in days)
        result.append({"date":key,"confirmed_orders":count,"confirmed_revenue":_money(revenue),"clicks":clicks})
    return result


def rule_based_insights(metrics:dict,creators:list[dict],products:list[dict]):
    insights=[]
    for creator in creators:
        clicks=creator["clicks"];orders=creator["orders"];confirmed=creator["confirmed_orders"]
        if clicks>=25 and confirmed==0:insights.append({"type":"high_traffic_low_conversion","subject":creator["creator"],"text":"This creator has at least 25 recorded clicks and no confirmed conversions in the selected period. Audience fit, offer, and landing experience may be worth reviewing.","rule":"clicks >= 25 and confirmed_orders == 0"})
        elif clicks<5:insights.append({"type":"low_traffic","subject":creator["creator"],"text":"Fewer than five referral clicks were recorded in this period; more exposure or link distribution may be needed before conversion comparisons are meaningful.","rule":"clicks < 5"})
        if orders>=3 and creator["cancellation_rate_pct"] and Decimal(creator["cancellation_rate_pct"])>=Decimal("30.00"):
            insights.append({"type":"high_cancellation_rate","subject":creator["creator"],"text":"At least three attributed orders and a cancellation rate of 30% or higher were recorded. Review order and offer context; this is an observation, not a causal finding.","rule":"orders >= 3 and cancellation_rate >= 30%"})
    if products:
        winner=max(products,key=lambda row:Decimal(row["confirmed_revenue"]))
        if Decimal(winner["confirmed_revenue"])>0:insights.append({"type":"product_revenue_leader","subject":winner["product"],"text":"This product has the highest confirmed attributed revenue among products with tracked eligible order items in the selected period.","rule":"max confirmed_revenue among campaign products"})
    if metrics["reward_efficiency"]["available"] and Decimal(metrics["reward_efficiency"]["ratio"])>1:
        insights.append({"type":"reward_efficiency","subject":"Campaign","text":"Confirmed attributed revenue is greater than generated non-demo reward value. This is reward efficiency, not full marketing ROI.","rule":"confirmed_revenue / generated_reward_value > 1"})
    return insights
