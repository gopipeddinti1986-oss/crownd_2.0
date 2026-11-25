from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "CROWND API"
    database_url: str = "sqlite:///./crownd.db"
    jwt_secret: str = "development-only-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cors_origins: str = "http://localhost:5173"
    cookie_secure: bool | None = None
    cookie_domain: str | None = None
    cookie_samesite: str = "lax"
    attribution_days: int = 7
    minimum_payout: str = "500.00"
    payment_mode: str = "simulator"
    app_env: str = "development"
    rate_limit_storage_uri: str = "memory://"
    rate_limit_enabled: bool = True
    trusted_proxy_ips: str = "127.0.0.1,::1"
    email_mode: str = "disabled"
    frontend_base_url: str = "http://localhost:5173"
    email_from: str = "CROWND <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    verification_token_hours: int = 24
    password_reset_token_minutes: int = 30
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def use_secure_cookies(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.is_production

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.cookie_samesite.lower() not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE must be lax, strict, or none")
        if self.email_mode not in {"disabled", "smtp"}:
            raise ValueError("EMAIL_MODE must be disabled or smtp")
        if self.cookie_samesite.lower()=="none" and not self.use_secure_cookies:
            raise ValueError("SameSite=None cookies require Secure")
        if self.access_token_minutes < 1 or self.refresh_token_days < 1:
            raise ValueError("Access and refresh token lifetimes must be positive")
        if self.email_mode == "smtp" and (not self.smtp_host or not self.email_from):
            raise ValueError("SMTP mode requires SMTP_HOST and EMAIL_FROM")
        if self.is_production:
            if len(self.jwt_secret) < 32 or self.jwt_secret == "development-only-change-me":
                raise ValueError("Production requires a unique JWT_SECRET of at least 32 characters")
            if not self.use_secure_cookies:
                raise ValueError("Production refresh cookies must use Secure")
            origins=[origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
            if not origins or "*" in origins:
                raise ValueError("Production CORS_ORIGINS must be an explicit origin allowlist")
            if not self.rate_limit_enabled or self.rate_limit_storage_uri.startswith("memory://"):
                raise ValueError("Production authentication rate limits require enabled shared storage such as Redis")
            if not self.trusted_proxy_ips.strip():
                raise ValueError("Production must explicitly configure trusted proxy IPs")
            if self.email_mode != "smtp":
                raise ValueError("Production requires a configured SMTP email provider for verification and recovery")
            if not self.smtp_starttls:
                raise ValueError("Production SMTP must use STARTTLS")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
            if any(not origin.startswith("https://") for origin in origins):
                raise ValueError("Production browser origins must use HTTPS")
            origins={origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()}
            if self.frontend_base_url.rstrip("/") not in origins:
                raise ValueError("FRONTEND_BASE_URL must be included in the explicit CORS_ORIGINS allowlist")
        return self

settings = Settings()
