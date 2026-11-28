from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import time
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.v1.auth import limiter
from app.core.config import settings
from app.database import get_db
from app.models.entities import AuditLog, BrandProfile, Campaign, CampaignProduct, Cart, CartItem, Conversion, Order, OrderItem, PaymentAttempt, Product, Referral, ReferralActivity, User
from app.schemas.commerce import CartItemRequest, CartQuantityRequest, CheckoutRequest, ProductCreate, ProductUpdate, ProductStatusUpdate, OrderStatusUpdate
from app.security import current_user, require_role
from app.services.payments import process_demo_payment
from app.services.referrals import attribution_state, campaign_is_active, eligible_product_ids, referral_eligibility, signed_referral_from_request, track_activity, visitor_hash
from app.services.conversions import create_conversion, transition_conversion
from app.services.rewards_engine import cancel_pending_collection_rewards, collect_cod_rewards, generate_order_rewards, self_referral
from app.services.notifications import create_notification

router = APIRouter()
REFERRAL_COOKIE = "crownd_referral"
CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _unit_price(product: Product) -> Decimal:
    return _money(product.sale_price if product.sale_price is not None else product.price)


def _brand_name(db: Session, product: Product) -> str:
    profile = db.scalar(select(BrandProfile).where(BrandProfile.user_id == product.brand_id))
    user = db.get(User, product.brand_id)
    return profile.name if profile else (user.name if user else "CROWND brand")


def _product_payload(db: Session, product: Product) -> dict:
    brand = db.get(User, product.brand_id)
    profile = db.scalar(select(BrandProfile).where(BrandProfile.user_id == product.brand_id))
    return {
        "id": product.id,
        "name": product.name,
        "slug": product.slug,
        "description": product.description,
        "category": product.category,
        "price": str(_money(product.price)),
        "sale_price": str(_money(product.sale_price)) if product.sale_price is not None else None,
        "effective_price": str(_unit_price(product)),
        "discount_percent": int((Decimal("100") * (product.price - product.sale_price) / product.price).quantize(Decimal("1"))) if product.sale_price is not None and product.price else 0,
        "stock": product.stock,
        "available": product.status == "active" and product.stock > 0 and bool(brand and brand.is_active),
        "status": product.status,
        "image_url": product.image_url,
        "image_urls": product.image_urls or ([product.image_url] if product.image_url else []),
        "specifications": product.specifications or {},
        "brand": {"id": brand.id, "name": profile.name if profile else brand.name, "website": profile.website if profile else ""} if brand else None,
    }


def _cart_for(db: Session, user: User) -> Cart:
    cart = db.scalar(select(Cart).where(Cart.user_id == user.id).with_for_update())
    if cart is None:
        cart = Cart(user_id=user.id)
        db.add(cart)
        db.flush()
    return cart


def _cart_payload(db: Session, cart: Cart, request: Request) -> dict:
    rows = db.execute(select(CartItem, Product).join(Product, Product.id == CartItem.product_id).where(CartItem.cart_id == cart.id).order_by(CartItem.id)).all()
    items = []
    subtotal = Decimal("0.00")
    invalid_items = 0
    for row, product in rows:
        unit = _unit_price(product)
        line = _money(unit * row.quantity)
        seller = db.get(User, product.brand_id)
        available = product.status == "active" and product.stock >= row.quantity and bool(seller and seller.role == "brand" and seller.is_active)
        subtotal += line
        invalid_items += int(not available)
        items.append({"id": row.id, "product": _product_payload(db, product), "quantity": row.quantity, "unit_price": str(unit), "line_total": str(line), "available": available})
    referral = _get_attribution(request, db)
    if referral and items and not any(referral_eligibility(db, referral, db.get(Product, entry["product"]["id"]))[0] for entry in items):
        referral = None
    return {"items": items, "item_count": sum(item["quantity"] for item in items), "subtotal": str(_money(subtotal)), "shipping": "0.00", "total": str(_money(subtotal)), "currency": "INR", "unavailable_count": invalid_items, "attribution": _referral_payload(db, referral) if referral else None}


def set_referral_cookie(response: Response, referral: Referral) -> None:
    expires = int(time.time()) + settings.attribution_days * 24 * 60 * 60
    response.set_cookie(key=REFERRAL_COOKIE, value=_sign_referral(referral.id, expires), max_age=settings.attribution_days * 24 * 60 * 60, path="/api/v1", secure=settings.use_secure_cookies, httponly=True, samesite=settings.cookie_samesite.lower(), domain=settings.cookie_domain or None)


def _sign_referral(referral_id: int, expires: int) -> str:
    message = f"{referral_id}.{expires}"
    signature = hmac.new(settings.jwt_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}.{signature}"


def _get_attribution(request: Request, db: Session) -> Referral | None:
    return signed_referral_from_request(request, db)


def _referral_payload(db: Session, referral: Referral) -> dict:
    creator = db.get(User, referral.creator_id)
    campaign = db.get(Campaign, referral.campaign_id)
    return {"creator_name": creator.name if creator else "Creator", "campaign": campaign.title if campaign else "Creator referral", "code": referral.code, "attribution_days": settings.attribution_days}


def _validate_referral_for_products(db: Session, referral: Referral | None, products: list[Product]) -> Referral | None:
    if referral is None:
        return None
    return referral if all(referral_eligibility(db, referral, product)[0] for product in products) else None


def _conversion_for_order(db: Session, order: Order) -> Conversion | None:
    return db.scalar(select(Conversion).where(Conversion.order_id == order.id))


def _payment_actor(db: Session, user_id: int | None) -> dict | None:
    user = db.get(User, user_id) if user_id else None
    return {"id": user.id, "name": user.name, "role": user.role} if user else None


def _order_payload(db: Session, order: Order, include_address: bool = True) -> dict:
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)).all()
    # Older one-line orders predate item snapshots; retain a compatible representation.
    line_items = [{"id": item.id, "product_id": item.product_id, "name": item.product_name, "brand": item.brand_name, "image_url": item.image_url, "unit_price": str(item.unit_price), "quantity": item.quantity, "line_total": str(item.line_total)} for item in items]
    if not line_items:
        product = db.get(Product, order.product_id)
        line_items = [{"product_id": order.product_id, "name": product.name if product else "Product", "brand": _brand_name(db, product) if product else "Brand", "image_url": product.image_url if product else "", "unit_price": str(_money(order.amount / max(order.quantity, 1))), "quantity": order.quantity, "line_total": str(_money(order.amount))}]
    attempts = db.scalars(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id).order_by(PaymentAttempt.attempt_number)).all()
    conversion = db.scalar(select(Conversion).where(Conversion.order_id == order.id))
    result = {"id": order.public_id, "order_id": order.public_id, "amount": str(_money(order.amount)), "currency": order.currency or "INR", "payment_method": order.payment_method or "legacy", "payment_status": order.payment_status, "transaction_reference": order.transaction_reference, "payment_confirmed_at": order.payment_confirmed_at.isoformat() if order.payment_confirmed_at else None, "payment_confirmed_by": _payment_actor(db, order.payment_confirmed_by), "payment_notes": order.payment_notes, "payment_attempts": [{"attempt_number": attempt.attempt_number, "payment_method": attempt.payment_method, "status": attempt.status, "amount": str(_money(attempt.amount)), "currency": attempt.currency, "transaction_reference": attempt.transaction_reference, "notes": attempt.notes, "created_at": attempt.created_at.isoformat(), "confirmed_at": attempt.confirmed_at.isoformat() if attempt.confirmed_at else None, "confirmed_by": _payment_actor(db, attempt.confirmed_by)} for attempt in attempts], "conversion": {"status": conversion.status, "is_demo": conversion.is_demo, "attributed_amount": str(_money(conversion.attributed_amount)), "reason": conversion.reason} if conversion else None, "status": order.status, "created_at": (order.created_at or datetime.now(timezone.utc)).isoformat(), "updated_at": (order.updated_at or order.created_at or datetime.now(timezone.utc)).isoformat(), "items": line_items, "referral": _referral_payload(db, db.get(Referral, order.referral_id)) if order.referral_id and db.get(Referral, order.referral_id) else None}
    if include_address:
        result["customer"] = {"name": order.customer_name, "email": order.customer_email}
        result["shipping_address"] = {"name": order.shipping_name, "phone": order.shipping_phone, "line1": order.shipping_line1, "line2": order.shipping_line2, "city": order.shipping_city, "state": order.shipping_state, "postal_code": order.shipping_postal_code, "country": order.shipping_country} if order.shipping_line1 else None
    return result


def _can_view_order(db: Session, order: Order, user: User) -> bool:
    if user.role == "admin":
        return True
    if order.customer_id == user.id or (order.customer_email.lower() == user.email.lower() and user.role == "customer"):
        return True
    if user.role == "brand":
        products = db.scalars(select(OrderItem.product_id).where(OrderItem.order_id == order.id, OrderItem.product_id.is_not(None))).all()
        product_ids = set(products) | {order.product_id}
        return bool(db.scalar(select(Product.id).where(Product.id.in_(product_ids), Product.brand_id == user.id).limit(1))) if product_ids else False
    if user.role == "creator" and order.referral_id:
        referral = db.get(Referral, order.referral_id)
        return bool(referral and referral.creator_id == user.id)
    return False


@router.get("/products/categories")
def product_categories(db: Session = Depends(get_db)):
    return db.scalars(select(Product.category).join(User, User.id == Product.brand_id).where(
        Product.status == "active", User.role == "brand", User.is_active.is_(True)
    ).distinct().order_by(Product.category)).all()


@router.get("/products/brands")
def product_brands(db: Session = Depends(get_db)):
    rows = db.execute(select(User.id, func.coalesce(BrandProfile.name, User.name)).join(Product, Product.brand_id == User.id).outerjoin(BrandProfile, BrandProfile.user_id == User.id).where(Product.status == "active", User.role == "brand", User.is_active.is_(True)).distinct().order_by(func.coalesce(BrandProfile.name, User.name))).all()
    return [{"id": user_id, "name": name} for user_id, name in rows]


@router.get("/brand/products")
def brand_product_catalog(page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_role("brand"))):
    stmt = select(Product).where(Product.brand_id == user.id)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    products = db.scalars(stmt.order_by(Product.created_at.desc(), Product.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_product_payload(db, product) for product in products], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


@router.patch("/brand/products/{product_id}")
def update_brand_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_db), user: User = Depends(require_role("brand"))):
    product = db.scalar(select(Product).where(Product.id == product_id, Product.brand_id == user.id).with_for_update())
    if not product:
        raise HTTPException(404, "Product not found")
    values = body.model_dump(exclude_unset=True)
    next_price = values.get("price", product.price)
    next_sale_price = values.get("sale_price", product.sale_price)
    if next_sale_price is not None and next_sale_price >= next_price:
        raise HTTPException(422, "Sale price must be below regular price")
    for field, value in values.items():
        setattr(product, field, value)
    try:
        db.add(AuditLog(actor_id=user.id, action="product.updated", entity_type="product", entity_id=str(product.id)))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Product update conflicts with existing catalog data") from None
    db.refresh(product)
    return _product_payload(db, product)


@router.patch("/brand/products/{product_id}/status")
def update_brand_product_status(product_id: int, body: ProductStatusUpdate, db: Session = Depends(get_db), user: User = Depends(require_role("brand"))):
    product = db.scalar(select(Product).where(Product.id == product_id, Product.brand_id == user.id).with_for_update())
    if not product:
        raise HTTPException(404, "Product not found")
    if body.status == product.status:
        return {"id": product.id, "status": product.status}
    if body.status == "inactive":
        linked_campaign = db.scalar(select(Campaign.id).outerjoin(CampaignProduct, CampaignProduct.campaign_id == Campaign.id).where(
            Campaign.brand_id == user.id,
            Campaign.status == "published",
            or_(Campaign.product_id == product.id, CampaignProduct.product_id == product.id),
        ).limit(1))
        if linked_campaign:
            raise HTTPException(409, "Pause or complete linked published campaigns before deactivating this product")
    product.status = body.status
    db.add(AuditLog(actor_id=user.id, action=f"product.{body.status}", entity_type="product", entity_id=str(product.id)))
    db.commit()
    return {"id": product.id, "status": product.status}


@router.get("/products")
def product_discovery(q: str | None = Query(default=None, max_length=120), category: str | None = Query(default=None, max_length=80), brand_id: int | None = Query(default=None, gt=0), min_price: Decimal | None = Query(default=None, ge=0), max_price: Decimal | None = Query(default=None, ge=0), in_stock: bool | None = None, campaign_id: int | None = Query(default=None, gt=0), sort: str = Query(default="newest", pattern="^(newest|price_asc|price_desc|name)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=12, ge=1, le=60), db: Session = Depends(get_db)):
    effective = func.coalesce(Product.sale_price, Product.price)
    stmt = select(Product).join(User, User.id == Product.brand_id).where(Product.status == "active", User.role == "brand", User.is_active.is_(True))
    if campaign_id is not None:
        campaign = db.get(Campaign, campaign_id)
        if not campaign or not campaign_is_active(campaign):
            raise HTTPException(status_code=404, detail="Campaign collection is not available")
        allowed_ids = eligible_product_ids(db, campaign)
        stmt = stmt.where(Product.id.in_(allowed_ids)) if allowed_ids else stmt.where(Product.id == -1)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where((Product.name.ilike(term)) | (Product.description.ilike(term)) | (Product.category.ilike(term)) | (select(BrandProfile.id).where(BrandProfile.user_id == User.id, BrandProfile.name.ilike(term)).exists()))
    if category:
        stmt = stmt.where(func.lower(Product.category) == category.strip().lower())
    if brand_id:
        stmt = stmt.where(Product.brand_id == brand_id)
    if min_price is not None:
        stmt = stmt.where(effective >= min_price)
    if max_price is not None:
        stmt = stmt.where(effective <= max_price)
    if in_stock is True:
        stmt = stmt.where(Product.stock > 0)
    elif in_stock is False:
        stmt = stmt.where(Product.stock <= 0)
    count = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_expr = {"newest": Product.created_at.desc(), "price_asc": effective.asc(), "price_desc": effective.desc(), "name": Product.name.asc()}[sort]
    products = db.scalars(stmt.order_by(sort_expr, Product.id.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_product_payload(db, product) for product in products], "total": count, "page": page, "page_size": page_size, "pages": (count + page_size - 1) // page_size}


@router.get("/products/{product_id}")
def product_detail(product_id: int, request: Request, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    brand = db.get(User, product.brand_id) if product else None
    if not product or product.status != "active" or not brand or brand.role != "brand" or not brand.is_active:
        raise HTTPException(status_code=404, detail="Product not found")
    payload = _product_payload(db, product)
    campaign = next((candidate for candidate in db.scalars(select(Campaign).where(Campaign.brand_id == product.brand_id, Campaign.status == "published").order_by(Campaign.created_at.desc())).all() if campaign_is_active(candidate) and product.id in eligible_product_ids(db, candidate)), None)
    if campaign:
        payload["creator_program"] = {"campaign": campaign.title, "reward_model": campaign.reward_model, "reward_rate": str(campaign.reward_rate), "active_creators": db.scalar(select(func.count(Referral.id)).where(Referral.campaign_id == campaign.id, Referral.active.is_(True))) or 0}
    else:
        payload["creator_program"] = None
    attribution = _get_attribution(request, db)
    referral = _validate_referral_for_products(db, attribution, [product])
    payload["attribution"] = _referral_payload(db, referral) if referral else None
    if referral:
        track_activity(db, request, referral, product, "product_view")
    related = db.scalars(select(Product).join(User, User.id == Product.brand_id).where(Product.status == "active", User.is_active.is_(True), Product.id != product.id, Product.category == product.category).order_by(Product.created_at.desc()).limit(4)).all()
    payload["related_products"] = [_product_payload(db, row) for row in related]
    db.commit()
    return payload


@router.get("/cart")
def get_cart(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cart = _cart_for(db, user)
    db.commit()
    return _cart_payload(db, cart, request)


@router.post("/cart/items", status_code=201)
@limiter.limit("30/minute")
def add_cart_item(body: CartItemRequest, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    product = db.get(Product, body.product_id)
    seller = db.get(User, product.brand_id) if product else None
    if not product or product.status != "active" or not seller or seller.role != "brand" or not seller.is_active:
        raise HTTPException(status_code=404, detail="Product is unavailable")
    cart = _cart_for(db, user)
    item = db.scalar(select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product.id).with_for_update())
    desired = body.quantity + (item.quantity if item else 0)
    if desired > min(product.stock, 99):
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Only {product.stock} item(s) are currently available")
    referral = _get_attribution(request, db)
    eligible_referral = referral if referral and referral_eligibility(db, referral, product)[0] else None
    if item:
        item.quantity = desired
        # A direct add never erases attribution; a new eligible referral at this
        # product touch may replace the item's previous referral.
        if eligible_referral: item.referral_id = eligible_referral.id
    else:
        db.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=desired, referral_id=eligible_referral.id if eligible_referral else None))
    cart.updated_at = datetime.now(timezone.utc)
    track_activity(db, request, referral, product, "cart_add")
    db.commit()
    db.refresh(cart)
    return _cart_payload(db, cart, request)


@router.patch("/cart/items/{item_id}")
@limiter.limit("30/minute")
def update_cart_item(item_id: int, body: CartQuantityRequest, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.scalar(select(CartItem).join(Cart, Cart.id == CartItem.cart_id).where(CartItem.id == item_id, Cart.user_id == user.id).with_for_update())
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    product = db.get(Product, item.product_id)
    seller = db.get(User, product.brand_id) if product else None
    if not product or product.status != "active" or not seller or seller.role != "brand" or not seller.is_active:
        raise HTTPException(status_code=409, detail="This product is no longer available")
    if body.quantity > product.stock:
        raise HTTPException(status_code=409, detail=f"Only {product.stock} item(s) are currently available")
    item.quantity = body.quantity
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _cart_payload(db, _cart_for(db, user), request)


@router.delete("/cart/items/{item_id}", status_code=204)
@limiter.limit("30/minute")
def remove_cart_item(item_id: int, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.scalar(select(CartItem).join(Cart, Cart.id == CartItem.cart_id).where(CartItem.id == item_id, Cart.user_id == user.id))
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    db.delete(item)
    db.commit()


@router.delete("/cart", status_code=204)
@limiter.limit("30/minute")
def clear_cart(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cart = db.scalar(select(Cart).where(Cart.user_id == user.id))
    if cart:
        db.execute(CartItem.__table__.delete().where(CartItem.cart_id == cart.id))
        db.commit()


@router.post("/checkout", status_code=201)
@limiter.limit("10/minute")
def checkout(body: CheckoutRequest, request: Request, response: Response, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100), db: Session = Depends(get_db), user: User = Depends(require_role("customer"))):
    if not all(char.isalnum() or char in "._:-" for char in idempotency_key):
        raise HTTPException(status_code=422, detail="Idempotency-Key contains unsupported characters")
    if body.payment_method == "online":
        raise HTTPException(status_code=409, detail="Online payment is coming soon and is not available")
    previous = db.scalar(select(Order).where(Order.customer_id == user.id, Order.idempotency_key == idempotency_key))
    if previous:
        response.status_code = 200
        return _order_payload(db, previous)
    cart = db.scalar(select(Cart).where(Cart.user_id == user.id).with_for_update())
    if not cart:
        raise HTTPException(status_code=409, detail="Your cart is empty")
    rows = db.execute(select(CartItem, Product, BrandProfile).join(Product, Product.id == CartItem.product_id).outerjoin(BrandProfile, BrandProfile.user_id == Product.brand_id).where(CartItem.cart_id == cart.id).order_by(CartItem.id).with_for_update(of=[CartItem, Product])).all()
    if not rows:
        raise HTTPException(status_code=409, detail="Your cart is empty")
    products = [product for _, product, _ in rows]
    subtotal = Decimal("0.00")
    for item, product, _brand in rows:
        seller = db.get(User, product.brand_id)
        if product.status != "active" or not seller or seller.role != "brand" or not seller.is_active or item.quantity > product.stock:
            raise HTTPException(status_code=409, detail=f"{product.name} is no longer available in the required quantity")
        subtotal += _money(_unit_price(product) * item.quantity)
    subtotal = _money(subtotal)
    referral = _get_attribution(request, db)
    visitor_state = attribution_state(db, request)
    visitor_id = visitor_state.visitor_hash if visitor_state else visitor_hash(request)
    if visitor_state and visitor_state.customer_id is None:
        visitor_state.customer_id = user.id
    address = body.shipping_address
    order = Order(public_id="CR-" + uuid4().hex[:12].upper(), customer_name=address.name, customer_email=user.email, customer_id=user.id, idempotency_key=idempotency_key, product_id=products[0].id, quantity=rows[0][0].quantity, amount=subtotal, currency="INR", payment_method=body.payment_method, referral_id=None, payment_status="pending" if body.payment_method == "demo" else "unpaid", status="pending" if body.payment_method == "demo" else "confirmed", shipping_name=address.name, shipping_phone=address.phone, shipping_line1=address.line1, shipping_line2=address.line2, shipping_city=address.city, shipping_state=address.state, shipping_postal_code=address.postal_code, shipping_country=address.country)
    db.add(order)
    db.flush()
    attributed_amount = Decimal("0.00")
    eligible_product_count = 0
    self_referral_seen = False
    selected_line_refs: list[Referral] = []
    for item, product, profile in rows:
        active_brand_ids = select(User.id).where(User.role == "brand", User.is_active.is_(True))
        changed = db.execute(update(Product).where(Product.id == product.id, Product.status == "active", Product.brand_id.in_(active_brand_ids), Product.stock >= item.quantity).values(stock=Product.stock - item.quantity).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"{product.name} sold out during checkout. Review your cart.")
        unit = _unit_price(product)
        brand = profile.name if profile else _brand_name(db, product)
        line_total = _money(unit * item.quantity)
        saved_referral = db.get(Referral, item.referral_id) if item.referral_id else None
        # The current valid touch can replace attribution on an eligible item;
        # otherwise retain the item-level referral captured when it was added.
        item_referral = None
        for candidate in (referral, saved_referral):
            if candidate and referral_eligibility(db, candidate, product)[0]:
                item_referral = candidate
                break
        item_referral_id = item_referral.id if item_referral else None
        if item_referral:
            selected_line_refs.append(item_referral)
            if self_referral(db,item_referral,user):
                self_referral_seen = True
            else:
                attributed_amount += line_total
                eligible_product_count += 1
        db.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name, brand_name=brand, image_url=product.image_url, unit_price=unit, quantity=item.quantity, line_total=line_total, referral_id=item_referral_id))
        db.delete(item)

    # Keep the order-level referral as a compatibility summary while rewards use
    # each order line's validated referral (multiple creators can share one order).
    primary_referral = referral if referral and any(ref.id==referral.id for ref in selected_line_refs) else (selected_line_refs[0] if selected_line_refs else None)
    order.referral_id = primary_referral.id if primary_referral else None
    conversion = None
    if primary_referral:
        conversion = create_conversion(db, order, primary_referral, visitor_hash=visitor_id, attributed_amount=attributed_amount,
            eligible_product_count=eligible_product_count, customer=user, self_referral_only=self_referral_seen and eligible_product_count==0)
    if body.payment_method == "demo":
        force_failure = request.headers.get("X-Demo-Payment-Test-Failure", "").lower() == "true"
        if force_failure and settings.app_env == "production":
            db.rollback()
            raise HTTPException(status_code=403, detail="Demo failure injection is disabled in production")
        result = process_demo_payment(force_failure=force_failure)
        paid_at = datetime.now(timezone.utc) if result.successful else None
        order.payment_status = "paid" if result.successful else "failed"
        order.status = "confirmed" if result.successful else "cancelled"
        order.transaction_reference = result.reference
        order.payment_confirmed_at = paid_at
        order.payment_notes = result.note
        db.add(PaymentAttempt(order_id=order.id, attempt_number=1, idempotency_key=idempotency_key, payment_method="demo", status=order.payment_status, amount=subtotal, currency="INR", transaction_reference=result.reference, notes=result.note, confirmed_at=paid_at))
        if not result.successful:
            for item, product, _profile in rows:
                db.execute(update(Product).where(Product.id == product.id).values(stock=Product.stock + item.quantity))
            transition_conversion(db, conversion, "cancelled", event_key=f"demo-failed:{order.id}", event_type="payment_failed", reason="demo_payment_failed")
        else:
            transition_conversion(db, conversion, "confirmed", event_key=f"demo-confirmed:{order.id}", event_type="demo_payment_confirmed", reason="simulated_success")
            generate_order_rewards(db,order,stage="demo")
    else:
        db.add(PaymentAttempt(order_id=order.id, attempt_number=1, idempotency_key=idempotency_key, payment_method="cod", status="unpaid", amount=subtotal, currency="INR", notes="Payment will be collected on delivery."))

    if body.payment_method == "cod":
        title = "Order placed"
        notice = f"Order {order.public_id} was placed with cash on delivery. No payment has been collected; cash collection is recorded only after delivery."
    elif order.payment_status == "paid":
        title = "Demo order confirmed"
        notice = f"The demo payment simulation recorded success for order {order.public_id}. No real money was charged or transferred."
    else:
        title = "Demo payment failed"
        notice = f"The demo payment simulation failed for order {order.public_id}; the order was cancelled and inventory restored. No real money was charged."
    create_notification(db, recipient_id=user.id, event_key=f"order-created:{order.id}", category="order",
        title=title, body=notice, action_path=f"/orders/{order.public_id}",
        email_subject=title, email_body=notice)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(Order).where(Order.customer_id == user.id, Order.idempotency_key == idempotency_key))
        if duplicate:
            response.status_code = 200
            return _order_payload(db, duplicate)
        raise HTTPException(status_code=409, detail="Checkout could not be completed; retry with a new idempotency key")
    db.refresh(order)
    return _order_payload(db, order)


@router.get("/orders")
def list_orders(db: Session = Depends(get_db), user: User = Depends(current_user), view: str = Query(default="business", pattern="^(business|customer)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)):
    if view == "customer" or user.role == "customer":
        stmt = select(Order).where((Order.customer_id == user.id) | ((Order.customer_id.is_(None)) & (Order.customer_email == user.email)))
    elif user.role == "admin":
        stmt = select(Order)
    elif user.role == "brand":
        owned_products = select(Product.id).where(Product.brand_id == user.id)
        brand_order_lines = select(OrderItem.order_id).join(Product, Product.id == OrderItem.product_id).where(Product.brand_id == user.id)
        # Mixed carts store only the first product on the legacy Order row; use line
        # snapshots as the source of truth while retaining support for pre-snapshot rows.
        stmt = select(Order).where(or_(Order.product_id.in_(owned_products), Order.id.in_(brand_order_lines)))
    elif user.role == "creator":
        stmt = select(Order).join(Referral, Referral.id == Order.referral_id).where(Referral.creator_id == user.id)
    else:
        stmt = select(Order).where(Order.customer_id == user.id)
    customer_view = view == "customer" or user.role == "customer"
    if not customer_view:
        # Keep established business-reporting pagination/shape for existing clients.
        business_orders = db.scalars(stmt.order_by(Order.created_at.desc())).all()
        return [{"id": order.public_id, "product_id": order.product_id, "quantity": order.quantity, "amount": float(order.amount), "payment_status": order.payment_status, "status": order.status, "created_at": order.created_at.isoformat()} for order in business_orders]
    count = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    orders = db.scalars(stmt.order_by(Order.created_at.desc(), Order.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_order_payload(db, order, include_address=order.customer_id == user.id) for order in orders], "total": count, "page": page, "page_size": page_size, "pages": (count + page_size - 1) // page_size}


@router.get("/admin/orders")
@limiter.limit("60/minute")
def admin_list_orders(request: Request, response: Response, q: str | None = Query(default=None, max_length=120), status: str | None = None, payment_status: str | None = None, payment_method: str | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    stmt = select(Order)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Order.public_id.ilike(term), Order.customer_name.ilike(term), Order.customer_email.ilike(term)))
    if status:
        stmt = stmt.where(Order.status == status)
    if payment_status:
        stmt = stmt.where(Order.payment_status == payment_status)
    if payment_method:
        stmt = stmt.where(Order.payment_method == payment_method)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    orders = db.scalars(stmt.order_by(Order.created_at.desc(), Order.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_order_payload(db, order) for order in orders], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


@router.get("/admin/orders/{order_id}")
@limiter.limit("60/minute")
def admin_get_order(order_id: str, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    order = db.scalar(select(Order).where(Order.public_id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_payload(db, order)


@router.post("/admin/orders/{order_id}/collect-payment")
@limiter.limit("10/minute")
def admin_collect_cod_payment(order_id: str, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    order = db.scalar(select(Order).where(Order.public_id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_method != "cod":
        raise HTTPException(status_code=409, detail="Only cash-on-delivery orders can be marked collected")
    if order.status != "delivered":
        raise HTTPException(status_code=409, detail="COD collection can only be confirmed after delivery")
    if order.payment_status != "unpaid":
        raise HTTPException(status_code=409, detail="COD payment has already been resolved")
    now = datetime.now(timezone.utc)
    reference = f"COD-COLLECT-{uuid4().hex[:12].upper()}"
    note = "Cash collection confirmed by an administrator; no digital transaction was performed."
    claimed = db.execute(update(Order).where(Order.id == order.id, Order.payment_method == "cod", Order.status == "delivered", Order.payment_status == "unpaid").values(payment_status="paid", transaction_reference=reference, payment_confirmed_at=now, payment_confirmed_by=user.id, payment_notes=note, updated_at=now).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="COD payment has already been resolved")
    attempt = db.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id).with_for_update())
    if attempt:
        attempt.status = "paid"
        attempt.transaction_reference = reference
        attempt.confirmed_at = now
        attempt.confirmed_by = user.id
        attempt.notes = note
    else:
        db.add(PaymentAttempt(order_id=order.id, attempt_number=1, idempotency_key=f"cod-collection:{order.public_id}", payment_method="cod", status="paid", amount=order.amount, currency=order.currency, transaction_reference=reference, notes=note, confirmed_at=now, confirmed_by=user.id))
    db.expire(order)
    conversion = _conversion_for_order(db, order)
    transition_conversion(db, conversion, "confirmed", event_key=f"cod-collected:{order.id}", event_type="cod_collection_confirmed", actor_id=user.id)
    collect_cod_rewards(db,order,user.id)
    db.add(AuditLog(actor_id=user.id, action="order.cod_payment_collected", entity_type="order", entity_id=order.public_id))
    if order.customer_id:
        notice = f"Cash collection for order {order.public_id} was recorded by an administrator after delivery. No digital transaction or payout occurred."
        create_notification(db, recipient_id=order.customer_id, event_key=f"cod-collected:{order.id}", category="order",
            title="Cash collection recorded", body=notice, action_path=f"/orders/{order.public_id}",
            email_subject="Cash collection recorded", email_body=notice)
    db.commit()
    db.refresh(order)
    return _order_payload(db, order)


@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = db.scalar(select(Order).where(Order.public_id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not _can_view_order(db, order, user):
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_payload(db, order, include_address=order.customer_id == user.id or user.role == "admin")


def _cancel_order_record(db: Session, order: Order, actor: User) -> dict:
    if order.status not in {"pending", "confirmed"}:
        raise HTTPException(status_code=409, detail="This order can no longer be cancelled")
    if order.payment_status == "paid":
        raise HTTPException(status_code=409, detail="Paid orders require a refund workflow and cannot be cancelled here")
    now = datetime.now(timezone.utc)
    payment_status = "not_required" if order.payment_method == "cod" else order.payment_status
    transitioned = db.execute(update(Order).where(Order.id == order.id, Order.status.in_(["pending", "confirmed"]), Order.payment_status != "paid").values(status="cancelled", payment_status=payment_status, updated_at=now).execution_options(synchronize_session=False))
    if transitioned.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="This order was already changed and can no longer be cancelled")
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).with_for_update()).all()
    if items:
        for item in items:
            if item.product_id is not None:
                db.execute(update(Product).where(Product.id == item.product_id).values(stock=Product.stock + item.quantity))
    else:
        db.execute(update(Product).where(Product.id == order.product_id).values(stock=Product.stock + order.quantity))
    order.status = "cancelled"
    order.payment_status = payment_status
    order.payment_notes = "COD obligation voided because the order was cancelled before collection." if order.payment_method == "cod" else order.payment_notes
    order.updated_at = now
    if order.payment_method == "cod":
        attempt = db.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id).with_for_update())
        if attempt:
            attempt.status = "not_required"
            attempt.notes = order.payment_notes
    if actor.role == "admin":
        db.add(AuditLog(actor_id=actor.id, action="order.cancelled_by_admin", entity_type="order", entity_id=order.public_id))
    conversion = _conversion_for_order(db, order)
    transition_conversion(db, conversion, "cancelled", event_key=f"order-cancelled:{order.id}", event_type="order_cancelled", actor_id=actor.id, reason="order_cancelled")
    cancel_pending_collection_rewards(db,order,actor.id)
    if order.customer_id:
        notice = f"Order {order.public_id} was cancelled in CROWND and eligible inventory was restored. No refund was processed."
        create_notification(db, recipient_id=order.customer_id, event_key=f"order-cancelled:{order.id}", category="order",
            title="Order cancelled", body=notice, action_path=f"/orders/{order.public_id}",
            email_subject="Order cancelled", email_body=notice)
    db.commit()
    return _order_payload(db, order)


@router.post("/orders/{order_id}/cancel")
@limiter.limit("10/minute")
def cancel_order(order_id: str, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = db.scalar(select(Order).where(Order.public_id == order_id).with_for_update())
    if not order or (user.role != "admin" and order.customer_id != user.id):
        raise HTTPException(status_code=404, detail="Order not found")
    return _cancel_order_record(db, order, user)


@router.post("/admin/orders/{order_id}/cancel")
@limiter.limit("10/minute")
def admin_cancel_order(order_id: str, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    order = db.scalar(select(Order).where(Order.public_id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _cancel_order_record(db, order, user)


@router.patch("/orders/{order_id}/status")
@limiter.limit("30/minute")
def update_order_status(order_id: str, body: OrderStatusUpdate, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    order = db.scalar(select(Order).where(Order.public_id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    transition = {"pending": {"confirmed"}, "confirmed": {"processing"}, "processing": {"shipped"}, "shipped": {"delivered"}}
    if body.status not in transition.get(order.status, set()):
        raise HTTPException(status_code=409, detail="Invalid order status transition")
    if body.status in {"processing", "shipped", "delivered"} and order.payment_status != "paid" and order.payment_method != "cod":
        raise HTTPException(status_code=409, detail="Fulfillment cannot advance until payment is confirmed; COD is collected separately on delivery")
    now = datetime.now(timezone.utc)
    claim = update(Order).where(Order.id == order.id, Order.status == order.status)
    if body.status in {"processing", "shipped", "delivered"} and order.payment_method != "cod":
        claim = claim.where(Order.payment_status == "paid")
    claimed = db.execute(claim.values(status=body.status, updated_at=now).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Order state changed; reload and retry")
    db.expire(order)
    db.add(AuditLog(actor_id=user.id, action=f"order.status.{body.status}", entity_type="order", entity_id=order.public_id))
    if order.customer_id:
        notice = f"Order {order.public_id} status was updated to {body.status} in CROWND by an administrator. Carrier tracking is not connected to this platform."
        create_notification(db, recipient_id=order.customer_id, event_key=f"order-status:{order.id}:{body.status}", category="order",
            title="Order status updated", body=notice, action_path=f"/orders/{order.public_id}",
            email_subject="Order status updated", email_body=notice)
    db.commit()
    db.refresh(order)
    return _order_payload(db, order)
