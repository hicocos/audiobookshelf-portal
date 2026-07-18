import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import Session

from app.auth_deps import require_admin
from app.db import get_session
from app.models import AuditLog
from app.settings_schema import PublicSettingsPatch
from app.services.settings import get_public_settings, settings_revision, update_public_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _patch_paths(value: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            paths.extend(_patch_paths(item, path))
        else:
            paths.append(path)
    return paths


def _patch_diff(
    current: dict[str, Any], patch: dict[str, Any], prefix: str = ""
) -> dict[str, dict[str, Any]]:
    diff: dict[str, dict[str, Any]] = {}
    for key, new_value in patch.items():
        path = f"{prefix}.{key}" if prefix else key
        old_value = current.get(key)
        if isinstance(new_value, dict) and isinstance(old_value, dict):
            diff.update(_patch_diff(old_value, new_value, path))
        elif old_value != new_value:
            diff[path] = {"before": old_value, "after": new_value}
    return diff


@router.get("/settings/public")
def read_public_settings(
    session: Session = Depends(get_session),
    _claims: dict = Depends(require_admin),
) -> dict:
    settings = get_public_settings(session)
    return {"settings": settings, "revision": settings_revision(settings)}


@router.patch("/settings/public")
def patch_public_settings(
    payload: PublicSettingsPatch,
    session: Session = Depends(get_session),
    claims: dict = Depends(require_admin),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict:
    # PATCH must preserve every field the caller did not send.  In particular,
    # nested Pydantic models otherwise serialize their optional members as
    # None, which deep_merge would treat as an explicit overwrite.
    patch = payload.model_dump(
        by_alias=True,
        exclude_unset=True,
        exclude_none=True,
    )
    current = get_public_settings(session)
    current_revision = settings_revision(current)
    if if_match is not None and if_match.strip('"') != current_revision:
        raise HTTPException(
            status_code=409,
            detail="设置已被其他管理员更新，请刷新后检查差异再保存。",
        )
    diff = _patch_diff(current, patch)
    updated = update_public_settings(
        session,
        patch,
        audit_log=AuditLog(
            actor_user_id=str(claims.get("sub") or "") or None,
            actor_username=str(claims.get("username") or "admin"),
            action="admin.settings.public.update",
            target_type="app_setting",
            target_id="public_settings",
            detail_json=json.dumps(
                {"fields": sorted(_patch_paths(patch)), "changes": diff},
                ensure_ascii=False,
            ),
        ),
    )
    return {"settings": updated, "revision": settings_revision(updated)}
