"""Shared campaign/referral eligibility and privacy-conscious attribution helpers."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
import hmac
import secrets
import time
from urllib.parse import urlsplit

from fastapi import Request, Response
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Application, Campaign, CampaignProduct, Click, Product, Referral, User, VisitorAttribution

REFERRAL_COOKIE = "crownd_referral"
VISITOR_COOKIE = "crownd_attribution"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def campaign_is_active(campaign: Campaign, at: datetime | None = None) -> bool:
    at = at or now_utc()
    starts = as_utc(campaign.starts_at)
    ends = as_utc(campaign.ends_at)
    return campaign.status == "published" and (starts is None or starts <= at) and (ends is None or ends >= at)


def eligible_product_ids(db: Session, campaign: Campaign) -> list[int]:
    listed = list(db.scalars(select(CampaignProduct.product_id).where(CampaignProduct.campaign_id == campaign.id)).all())
    if listed:
        # Explicit associations remain authoritative, but stale/deleted/inactive or
        # cross-brand products must not be exposed as currently eligible.
        return list(db.scalars(select(Product.id).where(Product.id.in_(listed),Product.brand_id==campaign.brand_id,Product.status=="active").order_by(Product.id)).all())
    if campaign.product_id:
        return list(db.scalars(select(Product.id).where(Product.id==campaign.product_id,Product.brand_id==campaign.brand_id,Product.status=="active")).all())
    # A campaign without an explicit product is a brand-wide active collection.
    return list(db.scalars(select(Product.id).where(Product.brand_id == campaign.brand_id, Product.status == "active").order_by(Product.id)).all())


def referral_eligibility(db: Session, referral: Referral, product: Product | None = None, *, at: datetime | None = None) -> tuple[bool, str | None]:
    at = at or now_utc()
    if not referral.active:
        return False, "inactive_link"
    creator = db.get(User, referral.creator_id)
    if not creator or creator.role!="creator" or not creator.is_active or not creator.email_verified:
        return False, "inactive_creator"
    campaign = db.get(Campaign, referral.campaign_id)
    if not campaign or not campaign_is_active(campaign, at):
        return False, "ineligible_campaign"
    application = db.scalar(select(Application).where(Application.campaign_id == campaign.id, Application.creator_id == creator.id))
    if not application or application.status != "accepted":
        return False, "unapproved_participation"
    brand = db.get(User, campaign.brand_id)
    if not brand or brand.role!="brand" or not brand.is_active:
        return False, "inactive_brand"
    allowed = set(eligible_product_ids(db, campaign))
    if referral.product_id is not None:
        if referral.product_id not in allowed:
            return False, "ineligible_product"
        allowed = {referral.product_id}
    if product is not None:
        if product.id not in allowed or product.brand_id != campaign.brand_id or product.status != "active":
            return False, "ineligible_product"
    elif not allowed:
        return False, "no_eligible_products"
    return True, None


def _signature(message: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), message.encode(), "sha256").hexdigest()


def _read_visitor(request: Request) -> tuple[str, str] | None:
    raw = request.cookies.get(VISITOR_COOKIE, "")
    try:
        token, expires_text, provided = raw.split(".", 2)
        expires = int(expires_text)
    except (ValueError, TypeError):
        return None
    if expires < int(time.time()) or not hmac.compare_digest(_signature(f"{token}.{expires}"), provided):
        return None
    return token, sha256(token.encode()).hexdigest()


def visitor_hash(request: Request) -> str | None:
    parsed = _read_visitor(request)
    return parsed[1] if parsed else None


def signed_referral_from_request(request: Request, db: Session) -> Referral | None:
    """Resolve the durable last-touch record, with old signed-cookie fallback."""
    parsed = _read_visitor(request)
    if parsed:
        state = db.scalar(select(VisitorAttribution).where(VisitorAttribution.visitor_hash == parsed[1]))
        if not state or not as_utc(state.expires_at) or as_utc(state.expires_at) < now_utc():
            return None
        if state.last_referral_id:
            return db.get(Referral, state.last_referral_id)
        return None
    # Compatibility with already-issued Phase 2 signed referral cookies.
    raw = request.cookies.get(REFERRAL_COOKIE, "")
    try:
        referral_text, expires_text, provided = raw.split(".", 2)
        referral_id, expires = int(referral_text), int(expires_text)
    except (ValueError, TypeError):
        return None
    if expires < int(time.time()) or not hmac.compare_digest(_signature(f"{referral_id}.{expires}"), provided):
        return None
    return db.get(Referral, referral_id)


def _safe_referrer_origin(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        return host[:255]
    except (ValueError, UnicodeError):
        return None


def _device_category(user_agent: str) -> str:
    agent = user_agent.lower()
    if not agent:
        return "unknown"
    if any(token in agent for token in ("bot", "crawler", "spider", "slurp")):
        return "bot"
    if "ipad" in agent or "tablet" in agent:
        return "tablet"
    if any(token in agent for token in ("mobile", "iphone", "android")):
        return "mobile"
    return "desktop"


def record_referral_click(db: Session, request: Request, response: Response, referral: Referral, destination: str) -> str:
    at = now_utc()
    parsed = _read_visitor(request)
    token = parsed[0] if parsed else secrets.token_urlsafe(32)
    hashed = sha256(token.encode()).hexdigest()
    expires_epoch = int(time.time()) + settings.attribution_days * 86400
    expires_at = datetime.fromtimestamp(expires_epoch, timezone.utc)
    state = db.scalar(select(VisitorAttribution).where(VisitorAttribution.visitor_hash == hashed).with_for_update())
    if state is None:
        state = VisitorAttribution(visitor_hash=hashed, first_referral_id=referral.id, last_referral_id=referral.id, first_touch_at=at, last_touch_at=at, expires_at=expires_at)
        db.add(state)
        db.flush()
    else:
        state.last_referral_id = referral.id
        state.last_touch_at = at
        state.expires_at = expires_at
    ua = request.headers.get("user-agent", "")[:500]
    click = Click(referral_id=referral.id, clicked_at=at, session_hash=hashed, destination=destination, referrer_origin=_safe_referrer_origin(request.headers.get("referer")), device_category=_device_category(ua), status="valid")
    db.add(click)
    db.execute(update(Referral).where(Referral.id == referral.id).values(clicks=Referral.clicks + 1))
    db.flush()
    visitor_value = f"{token}.{expires_epoch}.{_signature(f'{token}.{expires_epoch}')}"
    response.set_cookie(key=VISITOR_COOKIE, value=visitor_value, max_age=settings.attribution_days * 86400, path="/api/v1", secure=settings.use_secure_cookies, httponly=True, samesite=settings.cookie_samesite.lower(), domain=settings.cookie_domain or None)
    referral_value = f"{referral.id}.{expires_epoch}.{_signature(f'{referral.id}.{expires_epoch}')}"
    response.set_cookie(key=REFERRAL_COOKIE, value=referral_value, max_age=settings.attribution_days * 86400, path="/api/v1", secure=settings.use_secure_cookies, httponly=True, samesite=settings.cookie_samesite.lower(), domain=settings.cookie_domain or None)
    return hashed


def attribution_state(db: Session, request: Request) -> VisitorAttribution | None:
    parsed = _read_visitor(request)
    if not parsed:
        return None
    state = db.scalar(select(VisitorAttribution).where(VisitorAttribution.visitor_hash == parsed[1]))
    if not state or not as_utc(state.expires_at) or as_utc(state.expires_at) < now_utc():
        return None
    return state


def track_activity(db: Session, request: Request, referral: Referral | None, product: Product, event_type: str) -> None:
    hashed = visitor_hash(request)
    if not referral or not hashed or event_type not in {"product_view", "cart_add"}:
        return
    ok, _reason = referral_eligibility(db, referral, product)
    if ok:
        from app.models.entities import ReferralActivity
        db.add(ReferralActivity(referral_id=referral.id, visitor_hash=hashed, event_type=event_type, product_id=product.id))
        db.flush()


def generate_referral_code(db: Session) -> str:
    for _ in range(8):
        code = secrets.token_urlsafe(8).replace("-", "").replace("_", "").upper()[:10]
        if code and not db.scalar(select(Referral.id).where(func.upper(Referral.code) == code)):
            return code
    raise RuntimeError("Could not allocate a unique referral code")
