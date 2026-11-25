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
from app.models.entities import BrandProfile, Campaign, Cart, CartItem, Order, OrderItem, Product, Referral, User
from app.schemas.commerce import CartItemRequest, CartQuantityRequest, CheckoutRequest, OrderStatusUpdate
from app.security import current_user

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
        available = product.status == "active" and product.stock >= row.quantity
        subtotal += line
        invalid_items += int(not available)
        items.append({"id": row.id, "product": _product_payload(db, product), "quantity": row.quantity, "unit_price": str(unit), "line_total": str(line), "available": available})
    referral = _get_attribution(request, db)
    return {"items": items, "item_count": sum(item["quantity"] for item in items), "subtotal": str(_money(subtotal)), "shipping": "0.00", "total": str(_money(subtotal)), "currency": "INR", "unavailable_count": invalid_items, "attribution": _referral_payload(db, referral) if referral else None}


def set_referral_cookie(response: Response, referral: Referral) -> None:
    expires = int(time.time()) + settings.attribution_days * 24 * 60 * 60
    response.set_cookie(key=REFERRAL_COOKIE, value=_sign_referral(referral.id, expires), max_age=settings.attribution_days * 24 * 60 * 60, path="/api/v1", secure=settings.use_secure_cookies, httponly=True, samesite=settings.cookie_samesite.lower(), domain=settings.cookie_domain or None)


def _sign_referral(referral_id: int, expires: int) -> str:
    message = f"{referral_id}.{expires}"
    signature = hmac.new(settings.jwt_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}.{signature}"


def _get_attribution(request: Request, db: Session) -> Referral | None:
    raw = request.cookies.get(REFERRAL_COOKIE, "")
    try:
        referral_text, expires_text, provided = raw.split(".", 2)
        referral_id, expires = int(referral_text), int(expires_text)
    except (ValueError, TypeError):
        return None
    if expires < int(time.time()):
        return None
    expected = _sign_referral(referral_id, expires).rsplit(".", 1)[1]
    if not hmac.compare_digest(expected, provided):
        return None
    referral = db.get(Referral, referral_id)
    if not referral or not referral.active:
        return None
    creator = db.get(User, referral.creator_id)
    if not creator or not creator.is_active or not creator.email_verified:
        return None
    campaign = db.get(Campaign, referral.campaign_id)
    if not campaign or campaign.status != "published":
        return None
    return referral


def _referral_payload(db: Session, referral: Referral) -> dict:
    creator = db.get(User, referral.creator_id)
    campaign = db.get(Campaign, referral.campaign_id)
    return {"creator_name": creator.name if creator else "Creator", "campaign": campaign.title if campaign else "Creator referral", "code": referral.code, "attribution_days": settings.attribution_days}


def _validate_referral_for_products(db: Session, referral: Referral | None, products: list[Product]) -> Referral | None:
    if referral is None:
        return None
    campaign = db.get(Campaign, referral.campaign_id)
    creator = db.get(User, referral.creator_id)
    if not campaign or campaign.status != "published" or not referral.active or not creator or not creator.is_active or not creator.email_verified:
        return None
    if any(campaign.product_id not in (None, product.id) for product in products):
        return None
    return referral


def _order_payload(db: Session, order: Order, include_address: bool = True) -> dict:
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)).all()
    # Older one-line orders predate item snapshots; retain a compatible representation.
    line_items = [{"id": item.id, "product_id": item.product_id, "name": item.product_name, "brand": item.brand_name, "image_url": item.image_url, "unit_price": str(item.unit_price), "quantity": item.quantity, "line_total": str(item.line_total)} for item in items]
    if not line_items:
        product = db.get(Product, order.product_id)
        line_items = [{"product_id": order.product_id, "name": product.name if product else "Product", "brand": _brand_name(db, product) if product else "Brand", "image_url": product.image_url if product else "", "unit_price": str(_money(order.amount / max(order.quantity, 1))), "quantity": order.quantity, "line_total": str(_money(order.amount))}]
    result = {"id": order.public_id, "order_id": order.public_id, "amount": str(_money(order.amount)), "currency": "INR", "payment_status": order.payment_status, "status": order.status, "created_at": (order.created_at or datetime.now(timezone.utc)).isoformat(), "updated_at": (order.updated_at or order.created_at or datetime.now(timezone.utc)).isoformat(), "items": line_items, "referral": _referral_payload(db, db.get(Referral, order.referral_id)) if order.referral_id and db.get(Referral, order.referral_id) else None}
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
    return db.scalars(select(Product.category).where(Product.status == "active").distinct().order_by(Product.category)).all()


@router.get("/products/brands")
def product_brands(db: Session = Depends(get_db)):
    rows = db.execute(select(User.id, func.coalesce(BrandProfile.name, User.name)).join(Product, Product.brand_id == User.id).outerjoin(BrandProfile, BrandProfile.user_id == User.id).where(Product.status == "active", User.is_active.is_(True)).distinct().order_by(func.coalesce(BrandProfile.name, User.name))).all()
    return [{"id": user_id, "name": name} for user_id, name in rows]


@router.get("/products")
def product_discovery(q: str | None = Query(default=None, max_length=120), category: str | None = Query(default=None, max_length=80), brand_id: int | None = Query(default=None, gt=0), min_price: Decimal | None = Query(default=None, ge=0), max_price: Decimal | None = Query(default=None, ge=0), in_stock: bool | None = None, sort: str = Query(default="newest", pattern="^(newest|price_asc|price_desc|name)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=12, ge=1, le=60), db: Session = Depends(get_db)):
    effective = func.coalesce(Product.sale_price, Product.price)
    stmt = select(Product).join(User, User.id == Product.brand_id).where(Product.status == "active", User.is_active.is_(True))
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
    if not product or product.status != "active" or not brand or not brand.is_active:
        raise HTTPException(status_code=404, detail="Product not found")
    payload = _product_payload(db, product)
    campaign = db.scalar(select(Campaign).where(or_(Campaign.product_id == product.id, Campaign.product_id.is_(None)), Campaign.status == "published").order_by(Campaign.created_at.desc()))
    if campaign:
        payload["creator_program"] = {"campaign": campaign.title, "reward_model": campaign.reward_model, "reward_rate": str(campaign.reward_rate), "active_creators": db.scalar(select(func.count(Referral.id)).where(Referral.campaign_id == campaign.id, Referral.active.is_(True))) or 0}
    else:
        payload["creator_program"] = None
    attribution = _get_attribution(request, db)
    referral = _validate_referral_for_products(db, attribution, [product])
    payload["attribution"] = _referral_payload(db, referral) if referral else None
    related = db.scalars(select(Product).join(User, User.id == Product.brand_id).where(Product.status == "active", User.is_active.is_(True), Product.id != product.id, Product.category == product.category).order_by(Product.created_at.desc()).limit(4)).all()
    payload["related_products"] = [_product_payload(db, row) for row in related]
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
    if not product or product.status != "active":
        raise HTTPException(status_code=404, detail="Product is unavailable")
    cart = _cart_for(db, user)
    item = db.scalar(select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product.id).with_for_update())
    desired = body.quantity + (item.quantity if item else 0)
    if desired > min(product.stock, 99):
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Only {product.stock} item(s) are currently available")
    if item:
        item.quantity = desired
    else:
        db.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=desired))
    cart.updated_at = datetime.now(timezone.utc)
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
    if not product or product.status != "active":
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
def clear_cart(db: Session = Depends(get_db), user: User = Depends(current_user)):
    cart = db.scalar(select(Cart).where(Cart.user_id == user.id))
    if cart:
        db.execute(CartItem.__table__.delete().where(CartItem.cart_id == cart.id))
        db.commit()


@router.post("/checkout", status_code=201)
@limiter.limit("10/minute")
def checkout(body: CheckoutRequest, request: Request, response: Response, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100), db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not all(char.isalnum() or char in "._:-" for char in idempotency_key):
        raise HTTPException(status_code=422, detail="Idempotency-Key contains unsupported characters")
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
        if product.status != "active" or item.quantity > product.stock:
            raise HTTPException(status_code=409, detail=f"{product.name} no longer has enough inventory")
        subtotal += _money(_unit_price(product) * item.quantity)
    subtotal = _money(subtotal)
    referral = _validate_referral_for_products(db, _get_attribution(request, db), products)
    address = body.shipping_address
    order = Order(public_id="CR-" + uuid4().hex[:12].upper(), customer_name=address.name, customer_email=user.email, customer_id=user.id, idempotency_key=idempotency_key, product_id=products[0].id, quantity=rows[0][0].quantity, amount=subtotal, referral_id=referral.id if referral else None, payment_status="pending", status="pending", shipping_name=address.name, shipping_phone=address.phone, shipping_line1=address.line1, shipping_line2=address.line2, shipping_city=address.city, shipping_state=address.state, shipping_postal_code=address.postal_code, shipping_country=address.country)
    db.add(order)
    db.flush()
    for item, product, profile in rows:
        changed = db.execute(update(Product).where(Product.id == product.id, Product.status == "active", Product.stock >= item.quantity).values(stock=Product.stock - item.quantity).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"{product.name} sold out during checkout. Review your cart.")
        unit = _unit_price(product)
        brand = profile.name if profile else _brand_name(db, product)
        db.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name, brand_name=brand, image_url=product.image_url, unit_price=unit, quantity=item.quantity, line_total=_money(unit * item.quantity)))
        db.delete(item)
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
        stmt = select(Order).join(Product, Product.id == Order.product_id).where(Product.brand_id == user.id)
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


@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = db.scalar(select(Order).where(Order.public_id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not _can_view_order(db, order, user):
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_payload(db, order, include_address=order.customer_id == user.id or user.role == "admin")


@router.post("/orders/{order_id}/cancel")
@limiter.limit("10/minute")
def cancel_order(order_id: str, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = db.scalar(select(Order).where(Order.public_id == order_id).with_for_update())
    if not order or order.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in {"pending", "confirmed"}:
        raise HTTPException(status_code=409, detail="This order can no longer be cancelled")
    if order.payment_status == "paid":
        raise HTTPException(status_code=409, detail="Paid orders require a refund workflow and cannot be cancelled here")
    now = datetime.now(timezone.utc)
    transitioned = db.execute(update(Order).where(Order.id == order.id, Order.status.in_(["pending", "confirmed"]), Order.payment_status != "paid").values(status="cancelled", updated_at=now).execution_options(synchronize_session=False))
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
    order.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _order_payload(db, order)


@router.patch("/orders/{order_id}/status")
@limiter.limit("30/minute")
def update_order_status(order_id: str, body: OrderStatusUpdate, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = db.scalar(select(Order).where(Order.public_id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if user.role == "admin":
        allowed_actor = True
    elif user.role == "brand":
        allowed_actor = bool(db.scalar(select(Product.id).where(Product.id == order.product_id, Product.brand_id == user.id)))
    else:
        allowed_actor = False
    if not allowed_actor:
        raise HTTPException(status_code=404, detail="Order not found")
    transition = {"pending": {"confirmed"}, "confirmed": {"processing"}, "processing": {"shipped"}, "shipped": {"delivered"}}
    if body.status not in transition.get(order.status, set()):
        raise HTTPException(status_code=409, detail="Invalid order status transition")
    if body.status in {"processing", "shipped", "delivered"} and order.payment_status != "paid":
        raise HTTPException(status_code=409, detail="Fulfillment cannot advance until a trusted payment provider confirms payment")
    order.status = body.status
    order.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _order_payload(db, order)
