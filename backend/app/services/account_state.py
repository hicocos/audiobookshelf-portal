from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import AccountHold, PortalUser, utcnow

HOLD_KINDS = {"admin", "expired", "group", "inactivity", "legacy_unknown"}

HOLD_PRESENTATION: dict[str, tuple[str, str]] = {
    "admin": ("管理员停用", "请联系管理员确认恢复条件。"),
    "expired": ("账号已到期", "请使用续期码或联系管理员延长有效期。"),
    "group": ("必需群组资格暂停", "重新加入必需群组并等待资格同步。"),
    "inactivity": ("长期无收听活动", "请联系管理员确认后恢复。"),
    "legacy_unknown": ("历史停用原因待确认", "请联系管理员人工核实；系统不会自动恢复。"),
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def active_account_holds(session: Session, user: PortalUser) -> list[AccountHold]:
    return list(
        session.exec(
            select(AccountHold)
            .where(
                AccountHold.portal_user_id == user.id,
                AccountHold.active.is_(True),
            )
            .order_by(AccountHold.started_at, AccountHold.kind)
        ).all()
    )


def desired_account_status(
    session: Session,
    user: PortalUser,
    *,
    now: datetime | None = None,
) -> str:
    if user.status == "deleted":
        return "deleted"
    if user.telegram_binding_required and not user.telegram_id:
        return "pending"
    kinds = {item.kind for item in active_account_holds(session, user)}
    if kinds - {"expired"}:
        return "disabled"
    if "expired" in kinds:
        return "expired"
    expires_at = _aware(user.expires_at)
    if expires_at is not None and expires_at <= (now or utcnow()):
        return "expired"
    return "active"


def apply_desired_account_status(
    session: Session,
    user: PortalUser,
    *,
    now: datetime | None = None,
) -> str:
    next_status = desired_account_status(session, user, now=now)
    if user.status != next_status:
        user.status = next_status
        user.session_version = int(user.session_version or 0) + 1
        user.updated_at = now or utcnow()
        session.add(user)
    return next_status


def set_account_hold(
    session: Session,
    user: PortalUser,
    *,
    kind: str,
    actor: str | None,
    source: str,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> AccountHold:
    if kind not in HOLD_KINDS:
        raise ValueError(f"unsupported account hold kind: {kind}")
    timestamp = now or utcnow()
    hold = session.exec(
        select(AccountHold).where(
            AccountHold.portal_user_id == user.id,
            AccountHold.kind == kind,
        )
    ).first()
    if hold is None:
        hold = AccountHold(
            portal_user_id=user.id,
            kind=kind,
            actor=actor,
            source=source,
            metadata_json=(
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
                if metadata
                else None
            ),
            started_at=timestamp,
            updated_at=timestamp,
        )
    else:
        hold.active = True
        hold.started_at = timestamp
        hold.cleared_at = None
        hold.actor = actor
        hold.source = source
        hold.metadata_json = (
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
            if metadata
            else None
        )
        hold.updated_at = timestamp
    session.add(hold)
    session.flush()
    apply_desired_account_status(session, user, now=timestamp)
    return hold


def clear_account_hold(
    session: Session,
    user: PortalUser,
    *,
    kind: str,
    actor: str | None,
    source: str,
    now: datetime | None = None,
) -> AccountHold | None:
    timestamp = now or utcnow()
    hold = session.exec(
        select(AccountHold).where(
            AccountHold.portal_user_id == user.id,
            AccountHold.kind == kind,
        )
    ).first()
    if hold is not None and hold.active:
        hold.active = False
        hold.cleared_at = timestamp
        hold.actor = actor
        hold.source = source
        hold.updated_at = timestamp
        session.add(hold)
        session.flush()
    apply_desired_account_status(session, user, now=timestamp)
    return hold


def sync_expiry_hold(
    session: Session,
    user: PortalUser,
    *,
    actor: str | None,
    source: str,
    now: datetime | None = None,
) -> None:
    timestamp = now or utcnow()
    expires_at = _aware(user.expires_at)
    if expires_at is not None and expires_at <= timestamp:
        set_account_hold(
            session,
            user,
            kind="expired",
            actor=actor,
            source=source,
            metadata={"expiresAt": expires_at.isoformat()},
            now=timestamp,
        )
    else:
        clear_account_hold(
            session,
            user,
            kind="expired",
            actor=actor,
            source=source,
            now=timestamp,
        )


def serialize_account_holds(session: Session, user: PortalUser) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for hold in active_account_holds(session, user):
        label, recovery = HOLD_PRESENTATION.get(
            hold.kind,
            (hold.kind, "请联系管理员核实。"),
        )
        try:
            metadata = json.loads(hold.metadata_json or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        result.append(
            {
                "kind": hold.kind,
                "label": label,
                "recoveryAction": recovery,
                "startedAt": _aware(hold.started_at).isoformat(),
                "actor": hold.actor,
                "source": hold.source,
                "metadata": metadata,
            }
        )
    return result
