from decimal import Decimal
from datetime import datetime
from typing import Literal
import re
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

class CartItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=99)

class CartQuantityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: int = Field(ge=1, le=99)

class ShippingAddressInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=32)
    line1: str = Field(min_length=3, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    postal_code: str = Field(min_length=3, max_length=20)
    country: str = Field(default="IN", min_length=2, max_length=2)

    @field_validator("phone")
    @classmethod
    def phone_characters(cls, value: str) -> str:
        if not re.fullmatch(r"[+0-9() .-]{7,32}", value):
            raise ValueError("Enter a valid phone number")
        return value

    @field_validator("country")
    @classmethod
    def country_code(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("Use a two-letter country code")
        return value.upper()

class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shipping_address: ShippingAddressInput
    payment_method: Literal["demo", "cod", "online"]

class ProductCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=2, max_length=160)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    sale_price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    description: str = Field(default="", max_length=10000)
    category: str = Field(default="Other", min_length=2, max_length=80)
    stock: int = Field(default=0, ge=0, le=1000000)
    image_url: str = Field(default="", max_length=500)
    image_urls: list[str] = Field(default_factory=list, max_length=10)
    specifications: dict[str, str] = Field(default_factory=dict)

    @field_validator("sale_price")
    @classmethod
    def sale_below_price(cls, value: Decimal | None, info):
        price = info.data.get("price")
        if value is not None and price is not None and value >= price:
            raise ValueError("Sale price must be lower than the regular price")
        return value

class ProductOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str
    category: str
    price: Decimal
    sale_price: Decimal | None
    stock: int
    available: bool
    image_url: str
    image_urls: list[str]
    specifications: dict[str, str]
    brand: dict

class CampaignCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=2, max_length=180)
    product_id: int | None = Field(default=None, gt=0)
    product_ids: list[int] = Field(default_factory=list, max_length=50)
    description: str = Field(default="", max_length=10000)
    category: str = Field(default="Lifestyle", min_length=2, max_length=80)
    platforms: str = Field(default="Instagram", max_length=200)
    reward_model: str = Field(default="percentage", pattern=r"^(percentage|fixed)$")
    reward_rate: Decimal = Field(default=Decimal("10"), ge=0, max_digits=7, decimal_places=3)
    budget: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    objectives: list[str] = Field(default_factory=list, max_length=10)
    target_audience: str = Field(default="", max_length=500)
    creator_requirements: str = Field(default="", max_length=3000)
    visibility: Literal["public", "unlisted"] = "public"
    performance_goals: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("objectives")
    @classmethod
    def validate_objectives(cls, value: list[str]) -> list[str]:
        cleaned=[item.strip() for item in value if item.strip()]
        if len(cleaned)!=len(value) or any(len(item)>120 for item in cleaned):
            raise ValueError("Objectives must be non-empty and at most 120 characters")
        return cleaned

    @field_validator("performance_goals")
    @classmethod
    def validate_performance_goals(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        allowed={"confirmed_revenue","confirmed_conversions","clicks","conversion_rate_pct","reward_efficiency"}
        if set(value)-allowed or any(amount<0 for amount in value.values()):
            raise ValueError("Performance goals contain an unsupported metric or negative target")
        if "conversion_rate_pct" in value and value["conversion_rate_pct"]>100:
            raise ValueError("Conversion rate goal cannot exceed 100 percent")
        return value

    @field_validator("product_ids")
    @classmethod
    def unique_campaign_products(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value) or len(value) != len(set(value)):
            raise ValueError("Product IDs must be positive and unique")
        return value

    @field_validator("ends_at")
    @classmethod
    def end_after_start(cls, value, info):
        start = info.data.get("starts_at")
        if value and start and value <= start:
            raise ValueError("Campaign end must follow its start")
        return value

class CampaignStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["published", "paused", "completed", "cancelled", "rejected"]


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=10000)
    category: str | None = Field(default=None, min_length=2, max_length=80)
    platforms: str | None = Field(default=None, max_length=200)
    reward_model: Literal["percentage", "fixed"] | None = None
    reward_rate: Decimal | None = Field(default=None, ge=0, max_digits=7, decimal_places=3)
    budget: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    product_id: int | None = Field(default=None, gt=0)
    product_ids: list[int] | None = Field(default=None, max_length=50)
    objectives: list[str] | None = Field(default=None, max_length=10)
    target_audience: str | None = Field(default=None, max_length=500)
    creator_requirements: str | None = Field(default=None, max_length=3000)
    visibility: Literal["public", "unlisted"] | None = None
    performance_goals: dict[str, Decimal] | None = None

    @field_validator("product_ids")
    @classmethod
    def validate_products(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (any(item<=0 for item in value) or len(value)!=len(set(value))):
            raise ValueError("Product IDs must be positive and unique")
        return value

    @field_validator("objectives")
    @classmethod
    def validate_objectives(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (any(not item.strip() or len(item.strip())>120 for item in value) or len([item.strip() for item in value])!=len(set(item.strip() for item in value))):
            raise ValueError("Objectives must be distinct, non-empty and at most 120 characters")
        return [item.strip() for item in value] if value is not None else None

    @field_validator("performance_goals")
    @classmethod
    def validate_goals(cls, value: dict[str, Decimal] | None) -> dict[str, Decimal] | None:
        allowed={"confirmed_revenue","confirmed_conversions","clicks","conversion_rate_pct","reward_efficiency"}
        if value is not None and (set(value)-allowed or any(amount<0 for amount in value.values())):
            raise ValueError("Performance goals contain an unsupported metric or negative target")
        if value is not None and value.get("conversion_rate_pct",Decimal(0))>100:
            raise ValueError("Conversion rate goal cannot exceed 100 percent")
        return value

    @field_validator("ends_at")
    @classmethod
    def update_end_after_start(cls, value, info):
        start=info.data.get("starts_at")
        if value and start and value<=start:raise ValueError("Campaign end must follow its start")
        return value


class ReferralLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: int = Field(gt=0)
    product_id: int | None = Field(default=None, gt=0)

class ReferralLinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool

class CampaignProductsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_ids: list[int] = Field(min_length=1, max_length=50)

    @field_validator("product_ids")
    @classmethod
    def unique_products(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value) or len(value) != len(set(value)):
            raise ValueError("Product IDs must be positive and unique")
        return value

class ReferralRiskReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern=r"^(reviewed|dismissed)$")

class RewardRuleCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    campaign_id: int = Field(gt=0)
    product_id: int | None = Field(default=None, gt=0)
    reward_type: Literal["percentage", "fixed"]
    rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=3)
    fixed_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: Literal["INR"] = "INR"
    minimum_eligible_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    max_reward: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    max_creator_total: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    max_campaign_total: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    active: bool = True
    valid_from: datetime | None = None
    valid_until: datetime | None = None

class RewardRuleUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    reward_type: Literal["percentage", "fixed"] | None = None
    rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=3)
    fixed_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: Literal["INR"] | None = None
    minimum_eligible_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    max_reward: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    max_creator_total: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    max_campaign_total: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    active: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

class RewardReviewAction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    reason: str | None = Field(default=None, max_length=240)

class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern=r"^(confirmed|processing|shipped|delivered)$")
