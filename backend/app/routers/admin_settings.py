import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import Session

from app.auth_deps import require_admin
from app.config import Settings
from app.db import get_session
from app.models import AppSetting, AuditLog, utcnow
from app.settings_schema import PublicSettingsPatch
from app.services.settings import (
    deep_merge,
    get_public_settings,
    settings_revision,
    update_public_settings,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
GROUP_POLICY_HEALTH_KEY = "group_policy_health"


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _validated_group_health(session: Session, group_id: str) -> dict[str, Any] | None:
    record = session.get(AppSetting, GROUP_POLICY_HEALTH_KEY)
    if record is None:
        return None
    try:
        value = json.loads(record.value_json)
        checked_at = datetime.fromisoformat(str(value["checkedAt"]).replace("Z", "+00:00"))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if (
        str(value.get("groupId") or "") != group_id
        or value.get("healthy") is not True
        or _aware(checked_at) < utcnow() - timedelta(minutes=15)
    ):
        return None
    return value


def _validate_group_policy_prerequisites(
    session: Session,
    current: dict[str, Any],
    settings: dict[str, Any],
) -> None:
    telegram = settings.get("telegram")
    telegram = telegram if isinstance(telegram, dict) else {}
    if not telegram.get("groupMembershipEnabled"):
        return
    group_id = str(telegram.get("requiredGroupId") or "").strip()
    invite_url = str(telegram.get("requiredGroupInviteUrl") or "").strip()
    scope = str(telegram.get("groupPolicyScope") or "")
    if not group_id:
        raise HTTPException(status_code=422, detail="启用必需群组前必须填写群组 ID。")
    if not invite_url.startswith("https://"):
        raise HTTPException(
            status_code=422,
            detail="启用必需群组前必须填写 HTTPS 群组邀请或帮助链接。",
        )
    if scope != "new_users_only":
        raise HTTPException(
            status_code=422,
            detail="群组策略范围当前固定为 new_users_only。",
        )
    current_telegram = current.get("telegram")
    current_telegram = current_telegram if isinstance(current_telegram, dict) else {}
    newly_enabled_or_changed = (
        not current_telegram.get("groupMembershipEnabled")
        or str(current_telegram.get("requiredGroupId") or "") != group_id
    )
    if newly_enabled_or_changed and _validated_group_health(session, group_id) is None:
        raise HTTPException(
            status_code=409,
            detail="启用前必须先通过群组健康检查，且 Bot 必须是该群管理员。",
        )


async def _telegram_group_health(group_id: str) -> dict[str, Any]:
    token = Settings().telegram_bot_token.strip()
    if not token:
        return {
            "healthy": False,
            "groupReachable": False,
            "botIsAdmin": False,
            "error": "telegram_bot_token_not_configured",
        }
    base_url = f"https://api.telegram.org/bot{token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            me_response = await client.get(f"{base_url}/getMe")
            me_response.raise_for_status()
            bot = me_response.json().get("result") or {}
            chat_response = await client.post(f"{base_url}/getChat", json={"chat_id": group_id})
            chat_response.raise_for_status()
            member_response = await client.post(
                f"{base_url}/getChatMember",
                json={"chat_id": group_id, "user_id": bot.get("id")},
            )
            member_response.raise_for_status()
            membership = member_response.json().get("result") or {}
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return {
            "healthy": False,
            "groupReachable": False,
            "botIsAdmin": False,
            "error": type(exc).__name__,
        }
    status = str(membership.get("status") or "")
    is_admin = status in {"administrator", "creator"}
    return {
        "healthy": is_admin,
        "groupReachable": True,
        "botIsAdmin": is_admin,
        "botId": str(bot.get("id") or ""),
        "botUsername": bot.get("username"),
        "membershipStatus": status,
        "error": None if is_admin else "bot_not_group_admin",
    }


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


@router.get("/group-policy/health")
async def group_policy_health(
    session: Session = Depends(get_session),
    _claims: dict = Depends(require_admin),
) -> dict[str, Any]:
    telegram = get_public_settings(session).get("telegram")
    telegram = telegram if isinstance(telegram, dict) else {}
    group_id = str(telegram.get("requiredGroupId") or "").strip()
    if not group_id:
        raise HTTPException(status_code=422, detail="请先保存群组 ID（保持策略关闭）。")
    result = await _telegram_group_health(group_id)
    checked_at = utcnow()
    payload = {
        **result,
        "groupId": group_id,
        "scope": "new_users_only",
        "checkedAt": checked_at.isoformat(),
    }
    record = session.get(AppSetting, GROUP_POLICY_HEALTH_KEY)
    if record is None:
        record = AppSetting(
            key=GROUP_POLICY_HEALTH_KEY,
            value_json=json.dumps(payload, ensure_ascii=False),
        )
    else:
        record.value_json = json.dumps(payload, ensure_ascii=False)
        record.updated_at = checked_at
    session.add(record)
    session.commit()
    return payload


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
    _validate_group_policy_prerequisites(session, current, deep_merge(current, patch))
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
