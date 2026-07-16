from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlmodel import Session, select

from app.models import AuditLog, PortalUser, utcnow


class AbsUserClient(Protocol):
    async def list_users(self) -> list[dict[str, Any]]: ...
    async def update_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...


def _ms_to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def latest_listen_at(upstream_user: dict[str, Any]) -> datetime | None:
    progress = upstream_user.get("mediaProgress")
    if not isinstance(progress, list):
        return None
    latest: datetime | None = None
    for item in progress:
        if not isinstance(item, dict):
            continue
        seen = _ms_to_datetime(item.get("lastUpdate"))
        if seen and (latest is None or seen > latest):
            latest = seen
    return latest


def should_disable_for_inactivity(
    portal_user: PortalUser,
    upstream_user: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    inactive_days: int = 30,
    new_user_grace_days: int = 7,
) -> tuple[bool, str]:
    now = now or utcnow()
    created_at = _aware(portal_user.created_at) or now
    if portal_user.role in {"admin", "root"}:
        return False, "管理员账号不参与活跃度停用"
    if portal_user.status != "active":
        return False, "账号不是正常状态"
    if not portal_user.abs_user_id:
        return False, "未绑定媒体账号"
    if upstream_user is None:
        return False, "未找到上游用户"
    if upstream_user.get("isActive") is False:
        return False, "上游账号已停用"

    grace_cutoff = now - timedelta(days=max(new_user_grace_days, 0))
    if created_at > grace_cutoff:
        return False, f"新用户宽限期 {new_user_grace_days} 天内不检测"

    latest = latest_listen_at(upstream_user)
    inactive_cutoff = now - timedelta(days=max(inactive_days, 1))
    if latest is None:
        return True, "超过宽限期后仍没有任何收听记录"
    if latest < inactive_cutoff:
        return True, f"最近收听时间超过 {inactive_days} 天"
    return False, "最近一个周期内有收听记录"


async def sync_inactive_users(
    session: Session,
    abs_client: AbsUserClient,
    *,
    enabled: bool,
    inactive_days: int = 30,
    new_user_grace_days: int = 7,
    actor: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "checked": 0, "disabled": 0, "candidates": []}

    upstream_users = await abs_client.list_users()
    by_id = {str(item.get("id")): item for item in upstream_users if item.get("id")}
    portal_users = session.exec(select(PortalUser).where(PortalUser.status == "active")).all()

    checked = 0
    disabled = 0
    candidates: list[dict[str, Any]] = []
    for user in portal_users:
        checked += 1
        upstream_user = by_id.get(str(user.abs_user_id)) if user.abs_user_id else None
        should_disable, reason = should_disable_for_inactivity(
            user,
            upstream_user,
            inactive_days=inactive_days,
            new_user_grace_days=new_user_grace_days,
        )
        latest = latest_listen_at(upstream_user or {})
        candidate = {
            "portalUserId": user.id,
            "username": user.username,
            "absUserId": user.abs_user_id,
            "shouldDisable": should_disable,
            "reason": reason,
            "latestListenAt": latest.isoformat() if latest else None,
            "createdAt": _aware(user.created_at).isoformat() if user.created_at else None,
        }
        candidates.append(candidate)
        if should_disable and not dry_run:
            await abs_client.update_user(str(user.abs_user_id), {"isActive": False})
            user.status = "disabled"
            user.session_version = int(user.session_version or 0) + 1
            user.updated_at = utcnow()
            session.add(user)
            session.add(AuditLog(
                actor_username=actor or "system",
                action="disable_inactive_user",
                target_type="portal_user",
                target_id=user.id,
                detail_json=(
                    f'{{"reason":"{reason}","inactiveDays":{inactive_days},'
                    f'"newUserGraceDays":{new_user_grace_days}}}'
                ),
            ))
            disabled += 1

    if not dry_run:
        session.commit()
    return {
        "enabled": True,
        "checked": checked,
        "disabled": disabled,
        "dryRun": dry_run,
        "inactiveDays": inactive_days,
        "newUserGraceDays": new_user_grace_days,
        "candidates": candidates,
    }
