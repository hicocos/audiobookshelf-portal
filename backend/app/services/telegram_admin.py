from fastapi import HTTPException
from sqlmodel import Session

from app.config import Settings
from app.models import PortalUser
from app.services.settings import get_public_settings
from app.services.telegram_binding import get_user_by_telegram_id


def configured_admin_ids(settings: Settings | None = None) -> set[str]:
    settings = settings or Settings()
    return {
        item.strip()
        for item in settings.telegram_admin_ids.split(",")
        if item.strip()
    }


def require_telegram_admin(session: Session, telegram_id: str) -> PortalUser:
    features = get_public_settings(session).get("telegram")
    features = features if isinstance(features, dict) else {}
    if features.get("adminEnabled", True) is False:
        raise HTTPException(status_code=403, detail="telegram admin is disabled")
    allowed = configured_admin_ids()
    normalized = str(telegram_id).strip()
    if not allowed or normalized not in allowed:
        raise HTTPException(status_code=403, detail="telegram administrator is not allowlisted")
    user = get_user_by_telegram_id(session, normalized)
    if user is None or user.role not in {"admin", "root"} or user.status != "active":
        raise HTTPException(status_code=403, detail="portal administrator binding required")
    return user
