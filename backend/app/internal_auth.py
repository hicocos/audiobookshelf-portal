import secrets

from fastapi import Header, HTTPException

from app.config import Settings


def require_internal_bot(authorization: str | None = Header(default=None)) -> None:
    settings = Settings()
    expected = settings.telegram_bot_internal_token
    if not expected:
        raise HTTPException(status_code=503, detail="Telegram bot internal API is not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing internal token")
    token = authorization.split(" ", 1)[1]
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid internal token")
