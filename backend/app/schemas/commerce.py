from decimal import Decimal
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

class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern=r"^(confirmed|processing|shipped|delivered)$")
