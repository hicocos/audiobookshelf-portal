from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    web_internal_api_base: str = Field(default="http://moyin-api:8000", alias="WEB_INTERNAL_API_BASE")
    telegram_bot_internal_token: str = Field(default="", alias="TELEGRAM_BOT_INTERNAL_TOKEN")
    portal_public_url: str = Field(default="https://moyin.cc", alias="PORTAL_PUBLIC_URL")
    telegram_welcome_image_url: str = Field(
        default="https://mikupan.com/f/30kbFd/IMG_20260712_090816_398.jpg",
        alias="TELEGRAM_WELCOME_IMAGE_URL",
    )
    telegram_notification_poll_seconds: int = Field(
        default=5,
        ge=1,
        le=300,
        alias="TELEGRAM_NOTIFICATION_POLL_SECONDS",
    )
    telegram_admin_ids: str = Field(default="", alias="TELEGRAM_ADMIN_IDS")
