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

class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern=r"^(confirmed|processing|shipped|delivered)$")
