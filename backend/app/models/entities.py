from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, Index, JSON, CheckConstraint, event
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuthActionToken(Base):
    __tablename__ = "auth_action_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(24), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class CreatorProfile(Base):
    __tablename__ = "creator_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    niche: Mapped[str] = mapped_column(String(80), default="Lifestyle")
    location: Mapped[str] = mapped_column(String(100), default="India")
    bio: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(40), default="Instagram")
    followers: Mapped[int] = mapped_column(Integer, default=0)
    engagement: Mapped[float] = mapped_column(default=0)
    availability: Mapped[bool] = mapped_column(Boolean, default=True)
    crown_score: Mapped[int] = mapped_column(Integer, default=500)
    trust_score: Mapped[int] = mapped_column(Integer, default=80)
    verification: Mapped[str] = mapped_column(String(24), default="unverified", nullable=False)

class BrandProfile(Base):
    __tablename__ = "brand_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    industry: Mapped[str] = mapped_column(String(80), default="Consumer")
    website: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    verification: Mapped[str] = mapped_column(String(24), default="unverified")

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="Other")
    price: Mapped[Decimal] = mapped_column(Numeric(12,2))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    image_urls: Mapped[list] = mapped_column(JSON, default=list)
    specifications: Mapped[dict] = mapped_column(JSON, default=dict)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("sale_price IS NULL OR (sale_price > 0 AND sale_price < price)", name="ck_product_sale_below_regular"),)

class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="Lifestyle")
    platforms: Mapped[str] = mapped_column(String(200), default="Instagram")
    reward_model: Mapped[str] = mapped_column(String(20), default="percentage")
    reward_rate: Mapped[Decimal] = mapped_column(Numeric(7,3), default=Decimal("10"))
    budget: Mapped[Decimal] = mapped_column(Numeric(12,2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    objectives: Mapped[list] = mapped_column(JSON, default=list)
    target_audience: Mapped[str] = mapped_column(String(500), default="")
    creator_requirements: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(16), default="public")
    performance_goals: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class CampaignProduct(Base):
    __tablename__ = "campaign_products"
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("campaign_id", "creator_id", name="uq_campaign_creator_application"),)

class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=True, index=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Click(Base):
    __tablename__ = "referral_clicks"
    id: Mapped[int] = mapped_column(primary_key=True)
    referral_id: Mapped[int] = mapped_column(ForeignKey("referrals.id"), index=True)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    session_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    destination: Mapped[str] = mapped_column(String(300), default="/shop")
    referrer_origin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_category: Mapped[str] = mapped_column(String(20), default="unknown")
    status: Mapped[str] = mapped_column(String(20), default="valid")

class VisitorAttribution(Base):
    __tablename__ = "visitor_attributions"
    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    first_referral_id: Mapped[int | None] = mapped_column(ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True, index=True)
    last_referral_id: Mapped[int | None] = mapped_column(ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    first_touch_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_touch_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class ReferralActivity(Base):
    __tablename__ = "referral_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    referral_id: Mapped[int] = mapped_column(ForeignKey("referrals.id", ondelete="RESTRICT"), index=True)
    visitor_hash: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(24), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (CheckConstraint("event_type IN ('product_view','cart_add')", name="ck_referral_activity_type"),)

class Conversion(Base):
    __tablename__ = "conversions"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), unique=True, index=True)
    referral_id: Mapped[int | None] = mapped_column(ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True, index=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    visitor_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    attributed_amount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (CheckConstraint("status IN ('pending','confirmed','cancelled','reversed','ineligible')", name="ck_conversion_status"),)

class ConversionEvent(Base):
    __tablename__ = "conversion_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversion_id: Mapped[int] = mapped_column(ForeignKey("conversions.id", ondelete="RESTRICT"), index=True)
    event_key: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("conversion_id", "event_key", name="uq_conversion_event_key"),)

class ReferralRiskFlag(Base):
    __tablename__ = "referral_risk_flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    risk_code: Mapped[str] = mapped_column(String(40), index=True)
    referral_id: Mapped[int | None] = mapped_column(ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True, index=True)
    conversion_id: Mapped[int | None] = mapped_column(ForeignKey("conversions.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    visitor_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    details: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (CheckConstraint("status IN ('open','reviewed','dismissed')", name="ck_referral_risk_status"),)

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    referral_id: Mapped[int | None] = mapped_column(ForeignKey("referrals.id"), nullable=True, index=True)
    payment_status: Mapped[str] = mapped_column(String(24), default="pending")
    payment_method: Mapped[str] = mapped_column(String(16), default="legacy")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    transaction_reference: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    payment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="payment_pending")
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shipping_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    shipping_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    shipping_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    shipping_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shipping_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shipping_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shipping_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("customer_id", "idempotency_key", name="uq_order_customer_idempotency"),
        CheckConstraint("payment_method IN ('demo','cod','online','legacy')", name="ck_orders_payment_method"),
        CheckConstraint("payment_status IN ('pending','unpaid','paid','failed','refunded','partially_refunded','not_required')", name="ck_orders_payment_status"),
    )

class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    payment_method: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    transaction_reference: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("order_id", "attempt_number", name="uq_payment_attempt_number"),
        UniqueConstraint("order_id", "idempotency_key", name="uq_payment_attempt_key"),
        CheckConstraint("attempt_number > 0", name="ck_payment_attempt_number_positive"),
        CheckConstraint("payment_method IN ('demo','cod','online')", name="ck_payment_attempt_method"),
        CheckConstraint("status IN ('unpaid','pending','paid','failed','refunded','partially_refunded','not_required')", name="ck_payment_attempt_status"),
    )

class Cart(Base):
    __tablename__ = "carts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    referral_id: Mapped[int | None] = mapped_column(ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("cart_id", "product_id", name="uq_cart_product"),)

class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    product_name: Mapped[str] = mapped_column(String(160))
    brand_name: Mapped[str] = mapped_column(String(120))
    image_url: Mapped[str] = mapped_column(String(500), default="")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12,2))
    quantity: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12,2))
    referral_id: Mapped[int | None] = mapped_column(ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True, index=True)

class RewardRule(Base):
    __tablename__ = "reward_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=True, index=True)
    scope_key: Mapped[str] = mapped_column(String(80), unique=True)
    reward_type: Mapped[str] = mapped_column(String(16))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(7,3), nullable=True)
    fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    minimum_eligible_amount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=Decimal("0.00"))
    max_reward: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    max_creator_total: Mapped[Decimal | None] = mapped_column(Numeric(14,2), nullable=True)
    max_campaign_total: Mapped[Decimal | None] = mapped_column(Numeric(14,2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (
        CheckConstraint("reward_type IN ('percentage','fixed')", name="ck_reward_rule_type"),
        CheckConstraint("currency = 'INR'", name="ck_reward_rule_currency"),
        CheckConstraint("minimum_eligible_amount >= 0", name="ck_reward_rule_minimum"),
        CheckConstraint("rate IS NULL OR (rate >= 0 AND rate <= 100)", name="ck_reward_rule_rate"),
        CheckConstraint("fixed_amount IS NULL OR fixed_amount >= 0", name="ck_reward_rule_fixed"),
    )

class Reward(Base):
    __tablename__ = "rewards"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    conversion_id: Mapped[int | None] = mapped_column(ForeignKey("conversions.id", ondelete="SET NULL"), nullable=True, index=True)
    referral_id: Mapped[int | None] = mapped_column(ForeignKey("referrals.id", ondelete="SET NULL"), nullable=True, index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    reward_rule_id: Mapped[int | None] = mapped_column(ForeignKey("reward_rules.id", ondelete="SET NULL"), nullable=True, index=True)
    source_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    eligible_amount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=Decimal("0.00"))
    excluded_amount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    reward_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reward_rate: Mapped[Decimal | None] = mapped_column(Numeric(7,3), nullable=True)
    fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    calculation_formula: Mapped[str | None] = mapped_column(String(240), nullable=True)
    rounding_rule: Mapped[str] = mapped_column(String(32), default="ROUND_HALF_UP")
    calculation_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    risk_status: Mapped[str] = mapped_column(String(20), default="clear", index=True)
    eligible_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class RewardEvent(Base):
    __tablename__ = "reward_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    reward_id: Mapped[int] = mapped_column(ForeignKey("rewards.id", ondelete="RESTRICT"), index=True)
    event_key: Mapped[str] = mapped_column(String(140))
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("reward_id", "event_key", name="uq_reward_event_key"),)

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    direction: Mapped[str] = mapped_column(String(16), default="credit")
    idempotency_key: Mapped[str | None] = mapped_column(String(140), unique=True, nullable=True)
    reward_id: Mapped[int | None] = mapped_column(ForeignKey("rewards.id", ondelete="SET NULL"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    conversion_id: Mapped[int | None] = mapped_column(ForeignKey("conversions.id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    reversal_of_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id", ondelete="RESTRICT"), nullable=True, unique=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SimulatedPayout(Base):
    __tablename__ = "simulated_payouts"
    id: Mapped[int] = mapped_column(primary_key=True)
    reward_id: Mapped[int] = mapped_column(ForeignKey("rewards.id", ondelete="RESTRICT"), unique=True, index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    reference: Mapped[str] = mapped_column(String(80), unique=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    disclosure: Mapped[str] = mapped_column(String(120), default="Simulation only — no actual money was transferred.")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

def _deny_ledger_mutation(*_args):
    raise ValueError("Ledger entries are immutable; append a reversal instead.")

event.listen(LedgerEntry, "before_update", _deny_ledger_mutation)
event.listen(LedgerEntry, "before_delete", _deny_ledger_mutation)
event.listen(RewardEvent, "before_update", _deny_ledger_mutation)
event.listen(RewardEvent, "before_delete", _deny_ledger_mutation)

class Payout(Base):
    __tablename__ = "payouts"
    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    status: Mapped[str] = mapped_column(String(24), default="requested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class AdminDispute(Base):
    __tablename__ = "admin_disputes"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True, index=True)
    conversion_id: Mapped[int | None] = mapped_column(ForeignKey("conversions.id", ondelete="RESTRICT"), nullable=True, index=True)
    reward_id: Mapped[int | None] = mapped_column(ForeignKey("rewards.id", ondelete="RESTRICT"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    summary: Mapped[str] = mapped_column(String(500))
    opened_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint("status IN ('open','under_review','resolved')", name="ck_admin_dispute_status"),)

class AdminDisputeEvent(Base):
    __tablename__ = "admin_dispute_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    dispute_id: Mapped[int] = mapped_column(ForeignKey("admin_disputes.id", ondelete="RESTRICT"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

def _deny_append_only_mutation(*_args):
    raise ValueError("Administrative history is append-only.")

event.listen(AuditLog, "before_update", _deny_append_only_mutation)
event.listen(AuditLog, "before_delete", _deny_append_only_mutation)
event.listen(AdminAuditEvent, "before_update", _deny_append_only_mutation)
event.listen(AdminAuditEvent, "before_delete", _deny_append_only_mutation)
event.listen(AdminDisputeEvent, "before_update", _deny_append_only_mutation)
event.listen(AdminDisputeEvent, "before_delete", _deny_append_only_mutation)

class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    category_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(1000))
    action_path: Mapped[str | None] = mapped_column(String(240), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (UniqueConstraint("recipient_id", "event_key", name="uq_notification_recipient_event"),)

class EmailDelivery(Base):
    __tablename__ = "email_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(32), index=True)
    essential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    encrypted_message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("recipient_id", "event_key", name="uq_email_delivery_recipient_event"),
        CheckConstraint("status IN ('pending','sending','sent','suppressed','failed')", name="ck_email_delivery_status"),
        CheckConstraint("attempt_count >= 0", name="ck_email_delivery_attempt_count"),
    )
