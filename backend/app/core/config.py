import ipaddress
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    app_name: str = "CROWND API"
    database_url: str = "sqlite:///./crownd.db"
    jwt_secret: str = "development-only-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cors_origins: str = "http://localhost:5173"
    trusted_hosts: str = "localhost,127.0.0.1,::1,testserver"
    cookie_secure: bool | None = None
    cookie_domain: str | None = None
    cookie_samesite: str = "lax"
    attribution_days: int = 7
    minimum_payout: str = "500.00"
    app_env: str = "development"
    log_level: str = "INFO"
    rate_limit_storage_uri: str = "memory://"
    rate_limit_enabled: bool = True
    trusted_proxy_ips: str = "127.0.0.1,::1"
    forwarded_allow_ips: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout_seconds: int = 15
    db_pool_recycle_seconds: int = 1800
    db_connect_timeout_seconds: int = 5
    email_mode: str = "disabled"
    frontend_base_url: str = "http://localhost:5173"
    email_from: str = "CROWND <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_timeout_seconds: int = 10
    verification_token_hours: int = 24
    password_reset_token_minutes: int = 30
    worker_heartbeat_file: str = "/tmp/crownd-worker-heartbeat"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def use_secure_cookies(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.is_production

    @model_validator(mode="after")
    def validate_settings(self):
        if self.cookie_samesite.lower() not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE must be lax, strict, or none")
        if self.cookie_samesite.lower() == "none" and not self.use_secure_cookies:
            raise ValueError("SameSite=None cookies require Secure")
        if self.email_mode not in {"disabled", "smtp"}:
            raise ValueError("EMAIL_MODE must be disabled or smtp")
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        if self.access_token_minutes < 1 or self.refresh_token_days < 1:
            raise ValueError("Access and refresh token lifetimes must be positive")
        if min(self.db_pool_size, self.db_pool_timeout_seconds, self.db_pool_recycle_seconds,
               self.db_connect_timeout_seconds) < 1 or self.db_max_overflow < 0:
            raise ValueError("Database pool and connection timeout settings are invalid")
        if not 1 <= self.smtp_timeout_seconds <= 120 or not 1 <= self.smtp_port <= 65535:
            raise ValueError("SMTP port/timeout settings are invalid")
        if self.smtp_starttls and not self.smtp_host and self.email_mode == "smtp":
            raise ValueError("SMTP mode requires SMTP_HOST and EMAIL_FROM")
        if self.email_mode == "smtp" and (not self.smtp_host or not self.email_from):
            raise ValueError("SMTP mode requires SMTP_HOST and EMAIL_FROM")
        if self.is_production:
            if len(self.jwt_secret) < 32 or self.jwt_secret == "development-only-change-me":
                raise ValueError("Production requires a unique JWT_SECRET of at least 32 characters")
            if not self.use_secure_cookies:
                raise ValueError("Production refresh cookies must use Secure")
            origins = [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]
            if not origins or "*" in origins:
                raise ValueError("Production CORS_ORIGINS must be an explicit origin allowlist")
            for origin in origins:
                parsed = urlsplit(origin)
                try:
                    _port = parsed.port
                except ValueError as exc:
                    raise ValueError("Production CORS origin contains an invalid port") from exc
                if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
                    raise ValueError("Production CORS origins must be explicit HTTPS origins without paths or credentials")
            frontend = urlsplit(self.frontend_base_url.rstrip("/"))
            try:
                _frontend_port = frontend.port
            except ValueError as exc:
                raise ValueError("Production FRONTEND_BASE_URL contains an invalid port") from exc
            if frontend.scheme != "https" or not frontend.hostname or frontend.path or frontend.query or frontend.fragment or frontend.username:
                raise ValueError("Production FRONTEND_BASE_URL must be an HTTPS origin")
            if self.frontend_base_url.rstrip("/") not in origins:
                raise ValueError("FRONTEND_BASE_URL must be included in the explicit CORS_ORIGINS allowlist")
            hosts = [host.strip().lower() for host in self.trusted_hosts.split(",") if host.strip()]
            if not hosts or any("*" in host or "/" in host or "://" in host for host in hosts):
                raise ValueError("Production TRUSTED_HOSTS must be an explicit host allowlist without wildcards")
            if set(hosts) & {"localhost", "127.0.0.1", "::1", "testserver"}:
                raise ValueError("Production TRUSTED_HOSTS must not include local development hosts")
            proxies = [proxy.strip() for proxy in self.trusted_proxy_ips.split(",") if proxy.strip()]
            if not proxies:
                raise ValueError("Production must explicitly configure trusted proxy IPs")
            try:
                for proxy in proxies:
                    ipaddress.ip_network(proxy, strict=False)
            except ValueError as exc:
                raise ValueError("TRUSTED_PROXY_IPS entries must be explicit IP addresses or CIDR networks") from exc
            forwarded_proxies = [proxy.strip() for proxy in self.forwarded_allow_ips.split(",") if proxy.strip()]
            if not forwarded_proxies or "*" in forwarded_proxies:
                raise ValueError("Production FORWARDED_ALLOW_IPS must explicitly list trusted proxy IPs/CIDRs; wildcard is forbidden")
            try:
                for proxy in forwarded_proxies:
                    ipaddress.ip_network(proxy, strict=False)
            except ValueError as exc:
                raise ValueError("FORWARDED_ALLOW_IPS entries must be explicit IP addresses or CIDR networks") from exc
            redis_url = urlsplit(self.rate_limit_storage_uri)
            if not self.rate_limit_enabled or redis_url.scheme != "rediss" or not redis_url.hostname:
                raise ValueError("Production rate limits require enabled TLS Redis shared storage (rediss://host)")
            if self.email_mode != "smtp":
                raise ValueError("Production requires a configured SMTP email provider for verification and recovery")
            if not self.smtp_starttls:
                raise ValueError("Production SMTP must use STARTTLS")
            try:
                db_url = make_url(self.database_url)
            except Exception as exc:
                raise ValueError("Production DATABASE_URL is invalid") from exc
            if not db_url.drivername.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
            if not db_url.host or not db_url.database:
                raise ValueError("Production DATABASE_URL must specify a PostgreSQL host and database")
            if db_url.query.get("sslmode") != "verify-full":
                raise ValueError("Production PostgreSQL DATABASE_URL must verify the TLS certificate and hostname (sslmode=verify-full)")
            if self.cookie_domain and self.cookie_domain.startswith("."):
                raise ValueError("COOKIE_DOMAIN must be a bare hostname without a leading dot")
        return self


settings = Settings()
