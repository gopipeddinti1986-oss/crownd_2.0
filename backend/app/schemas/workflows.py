from typing import Literal
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CreatorProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=120)
    username: str | None = Field(default=None, min_length=2, max_length=60)
    niche: str | None = Field(default=None, min_length=2, max_length=80)
    location: str | None = Field(default=None, min_length=2, max_length=100)
    bio: str | None = Field(default=None, max_length=5000)
    platform: str | None = Field(default=None, min_length=2, max_length=40)
    followers: int | None = Field(default=None, ge=0, le=2_000_000_000)
    engagement: float | None = Field(default=None, ge=0, le=100)
    availability: bool | None = None

    @field_validator("username")
    @classmethod
    def username_characters(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.-]{2,60}", value):
            raise ValueError("Username may contain only letters, numbers, periods, underscores and hyphens")
        return value

    @model_validator(mode="before")
    @classmethod
    def reject_null_updates(cls, value):
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("Profile fields cannot be null")
        return value

    @model_validator(mode="after")
    def at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one profile field to update")
        return self


class AccountProfileUpdate(BaseModel):
    """Strict role-aware account/profile update; role-specific fields are checked in the handler."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=120)
    username: str | None = Field(default=None, min_length=2, max_length=60)
    niche: str | None = Field(default=None, min_length=2, max_length=80)
    location: str | None = Field(default=None, min_length=2, max_length=100)
    bio: str | None = Field(default=None, max_length=5000)
    platform: str | None = Field(default=None, min_length=2, max_length=40)
    followers: int | None = Field(default=None, ge=0, le=2_000_000_000)
    engagement: float | None = Field(default=None, ge=0, le=100)
    availability: bool | None = None
    industry: str | None = Field(default=None, min_length=2, max_length=80)
    website: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("username")
    @classmethod
    def account_username_characters(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.-]{2,60}", value):
            raise ValueError("Username may contain only letters, numbers, periods, underscores and hyphens")
        return value

    @field_validator("website")
    @classmethod
    def safe_website_url(cls, value: str | None) -> str | None:
        if value:
            try:
                parsed = urlsplit(value)
                if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password or any(char.isspace() for char in value):
                    raise ValueError
            except ValueError:
                raise ValueError("Website must be an HTTPS URL without embedded credentials") from None
        return value

    @model_validator(mode="before")
    @classmethod
    def reject_null_and_empty_updates(cls, value):
        if isinstance(value, dict) and (not value or any(item is None for item in value.values())):
            raise ValueError("Provide one or more non-null profile fields")
        return value


class ApplicationSubmission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    message: str = Field(default="", max_length=2000)


class ApplicationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["shortlisted", "accepted", "rejected"]
