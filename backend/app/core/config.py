from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "CROWND API"
    database_url: str = "sqlite:///./crownd.db"
    jwt_secret: str = "development-only-change-me"
    access_token_minutes: int = 45
    cors_origins: str = "http://localhost:5173"
    attribution_days: int = 7
    minimum_payout: str = "500.00"
    payment_mode: str = "simulator"
    app_env: str = "development"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
