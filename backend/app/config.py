from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_JWT_SECRET = (
    "change-me-in-production-at-least-32-bytes"  # nosec B105
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    portal_public_url: str = "http://localhost:3009"
    app_env: str = Field(default="development", alias="APP_ENV")
    audiobookshelf_url: str = "http://127.0.0.1:13378"
    audiobookshelf_admin_token: str = ""
    database_url: str = "sqlite:////data/portal.db"
    jwt_secret: str = INSECURE_DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    session_cookie_name: str = Field(default="moyin_session", alias="SESSION_COOKIE_NAME")
    session_cookie_secure: bool = Field(default=False, alias="SESSION_COOKIE_SECURE")
    session_cookie_samesite: str = Field(default="lax", alias="SESSION_COOKIE_SAMESITE")
    registration_enabled: bool = True
    default_valid_days: int = 30
    portal_password_min_length: int = Field(default=3, alias="PORTAL_PASSWORD_MIN_LENGTH")
    next_public_site_name: str = Field(default="MoYin.CC", alias="NEXT_PUBLIC_SITE_NAME")
    cors_allowed_origins: str = Field(
        default="http://localhost:3009,http://127.0.0.1:3009",
        alias="CORS_ALLOWED_ORIGINS",
    )
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
    telegram_bot_internal_token: str = Field(default="", alias="TELEGRAM_BOT_INTERNAL_TOKEN")
    telegram_bind_code_ttl_minutes: int = Field(default=10, alias="TELEGRAM_BIND_CODE_TTL_MINUTES")
    telegram_bind_code_max_failures: int = Field(default=5, alias="TELEGRAM_BIND_CODE_MAX_FAILURES")
    telegram_search_scan_limit: int = Field(default=200, alias="TELEGRAM_SEARCH_SCAN_LIMIT")
    telegram_search_result_limit: int = Field(default=8, alias="TELEGRAM_SEARCH_RESULT_LIMIT")
    telegram_flow_ttl_minutes: int = Field(default=15, alias="TELEGRAM_FLOW_TTL_MINUTES")
    telegram_password_reset_ttl_minutes: int = Field(
        default=10,
        alias="TELEGRAM_PASSWORD_RESET_TTL_MINUTES",
    )
    telegram_admin_ids: str = Field(default="", alias="TELEGRAM_ADMIN_IDS")
    trusted_proxy_ips: str = Field(default="127.0.0.1,::1", alias="TRUSTED_PROXY_IPS")
    admin_setup_token: str = Field(default="", alias="ADMIN_SETUP_TOKEN")
    worker_health_state_path: str = Field(
        default="/data/worker-health.json",
        alias="WORKER_HEALTH_STATE_PATH",
    )
    worker_health_max_age_seconds: int = Field(
        default=900,
        alias="WORKER_HEALTH_MAX_AGE_SECONDS",
    )
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_interval_seconds: int = Field(
        default=300,
        ge=1,
        le=86400,
        alias="SCHEDULER_INTERVAL_SECONDS",
    )
    scheduler_lock_path: str = Field(
        default="/data/scheduler.lock",
        alias="SCHEDULER_LOCK_PATH",
    )

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env.lower() == "production" and self.jwt_secret == INSECURE_DEFAULT_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set to a strong random value in production")
        return self

    @property
    def public_audiobookshelf_url(self) -> str:
        return self.audiobookshelf_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
