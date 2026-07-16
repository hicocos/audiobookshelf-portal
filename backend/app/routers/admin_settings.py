from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.auth_deps import require_admin
from app.db import get_session
from app.models import utcnow
from app.routers.auth import get_abs_client_factory
from app.settings_schema import PublicSettingsPatch
from app.services.inactivity import sync_inactive_users
from app.services.settings import get_public_settings, update_public_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _clean_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


@router.get("/settings/public")
def read_public_settings(
    session: Session = Depends(get_session),
    _claims: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return {"settings": get_public_settings(session)}


@router.patch("/settings/public")
def patch_public_settings(
    payload: PublicSettingsPatch,
    session: Session = Depends(get_session),
    _claims: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    updated = update_public_settings(session, _clean_none(payload.model_dump(by_alias=True)))
    return {"settings": updated}


@router.post("/inactivity/check")
async def run_inactivity_check(
    session: Session = Depends(get_session),
    claims: dict[str, Any] = Depends(require_admin),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    settings = get_public_settings(session)
    operations = settings.get("operations") if isinstance(settings.get("operations"), dict) else {}
    enabled = bool(operations.get("inactivityAutoDisable"))
    inactive_days = int(operations.get("inactiveDays") or 30)
    grace_days = int(operations.get("newUserGraceDays") or 7)
    async with abs_factory() as abs_client:
        result = await sync_inactive_users(
            session,
            abs_client,
            enabled=enabled,
            inactive_days=inactive_days,
            new_user_grace_days=grace_days,
            actor=str(claims.get("sub") or "admin"),
            dry_run=False,
        )
    updated_settings = update_public_settings(session, {
        "operations": {
            **operations,
            "lastInactivityCheckAt": utcnow().isoformat(),
            "lastInactivityDisabled": result.get("disabled", 0),
        }
    })
    return {"result": result, "settings": updated_settings}
