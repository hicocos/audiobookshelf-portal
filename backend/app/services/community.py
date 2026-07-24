import json
from datetime import UTC, timedelta
from typing import Any

import httpx
from sqlmodel import Session, select

from app.models import AuditLog, PortalUser, TelegramGroupMembership, utcnow
from app.services.account_state import (
    clear_account_hold,
    desired_account_status,
    set_account_hold,
    sync_expiry_hold,
)
from app.services.reconciliation import enqueue_reconciliation_job
from app.services.telegram_notifications import enqueue_notification


def is_group_policy_applicable(
    user: PortalUser,
    telegram_settings: dict[str, Any] | None = None,
) -> bool:
    """Return the one policy decision shared by lifecycle and Bot gates.

    The production policy is intentionally fixed to new users only. Existing
    users remain grandfathered through ``telegram_binding_required=False``.
    """

    settings = telegram_settings or {}
    if not settings.get("groupMembershipEnabled", True):
        return False
    if str(settings.get("groupPolicyScope") or "new_users_only") != "new_users_only":
        return False
    return (
        user.role not in {"admin", "root"}
        and user.status != "deleted"
        and bool(user.telegram_binding_required)
    )


async def report_group_membership(
    session: Session,
    user: PortalUser,
    *,
    group_id: str,
    is_member: bool,
    grace_hours: int,
    abs_factory: Any,
) -> TelegramGroupMembership:
    now = utcnow()
    membership = session.exec(
        select(TelegramGroupMembership).where(
            TelegramGroupMembership.portal_user_id == user.id
        )
    ).first()
    if membership is None:
        membership = TelegramGroupMembership(
            portal_user_id=user.id,
            telegram_id=str(user.telegram_id or ""),
            group_id=group_id,
        )
        session.add(membership)
        session.flush()
    membership.telegram_id = str(user.telegram_id or membership.telegram_id)
    membership.group_id = group_id
    membership.last_checked_at = now
    membership.updated_at = now

    if is_member:
        was_group_disabled = membership.status == "disabled" and membership.disabled_at is not None
        group_disabled_at = membership.disabled_at
        if (
            was_group_disabled
            and group_disabled_at is not None
            and user.status == "disabled"
            and user.updated_at > group_disabled_at
        ):
            # Compatibility bridge for pre-hold data: a later manual disable must
            # survive group rejoin. Future admin actions create an explicit hold.
            set_account_hold(
                session,
                user,
                kind="admin",
                actor="legacy-migration",
                source="manual_disable_after_group",
                now=now,
            )
        membership.status = "member"
        membership.left_at = None
        membership.grace_expires_at = None
        membership.disabled_at = None
        sync_expiry_hold(
            session,
            user,
            actor="telegram-group-sync",
            source="group_rejoin",
            now=now,
        )
        clear_account_hold(
            session,
            user,
            kind="group",
            actor="telegram-group-sync",
            source="group_rejoin",
            now=now,
        )
        if was_group_disabled and desired_account_status(session, user, now=now) == "active":
            if user.abs_user_id:
                try:
                    async with abs_factory() as abs_client:
                        await abs_client.update_user(user.abs_user_id, {"isActive": True})
                except (httpx.HTTPError, TypeError, RuntimeError):
                    enqueue_reconciliation_job(
                        session,
                        idempotency_key=f"group-rejoin:{membership.id}:{now.isoformat()}",
                        operation="set_active",
                        target_type="portal_user",
                        target_id=user.id,
                        abs_user_id=user.abs_user_id,
                        payload={"isActive": True, "source": "group_rejoin"},
                    )
            session.add(
                AuditLog(
                    actor_username="telegram-group-sync",
                    action="telegram.group.rejoin_enable",
                    target_type="portal_user",
                    target_id=user.id,
                )
            )
    elif not is_group_policy_applicable(
        user,
        {
            "groupMembershipEnabled": True,
            "groupPolicyScope": "new_users_only",
        },
    ):
        clear_account_hold(
            session,
            user,
            kind="group",
            actor="telegram-group-sync",
            source="scope_exempt",
            now=now,
        )
        membership.status = "exempt"
        membership.left_at = now
        membership.grace_expires_at = None
        membership.disabled_at = None
    elif membership.status not in {"grace", "disabled"}:
        membership.status = "grace"
        membership.left_at = now
        membership.grace_expires_at = now + timedelta(hours=max(1, grace_hours))
        session.add(
            AuditLog(
                actor_username="telegram-group-sync",
                action="telegram.group.grace_start",
                target_type="portal_user",
                target_id=user.id,
                detail_json=json.dumps(
                    {"groupId": group_id, "graceHours": grace_hours},
                    ensure_ascii=False,
                ),
            )
        )
        if user.telegram_id:
            enqueue_notification(
                session,
                dedupe_key=f"group-grace:{membership.id}:{membership.grace_expires_at.isoformat()}",
                telegram_id=user.telegram_id,
                kind="group_grace",
                message=(
                    f"检测到你已离开必需群组。请在 {grace_hours} 小时内重新加入，"
                    "否则媒体账号会自动停用；重新加入后会自动恢复。"
                ),
            )
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return membership


async def enforce_group_grace_periods(
    session: Session,
    abs_client: Any,
) -> dict[str, int]:
    now = utcnow()
    active_grace = session.exec(
        select(TelegramGroupMembership).where(
            TelegramGroupMembership.status == "grace",
            TelegramGroupMembership.grace_expires_at.is_not(None),
            TelegramGroupMembership.grace_expires_at > now,
        )
    ).all()
    for membership in active_grace:
        if not membership.telegram_id or membership.grace_expires_at is None:
            continue
        deadline = membership.grace_expires_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        hours_left = (deadline - now).total_seconds() / 3600
        boundary = 6 if hours_left <= 6 else 24 if hours_left <= 24 else None
        if boundary is None:
            continue
        enqueue_notification(
            session,
            dedupe_key=f"group-grace-reminder:{membership.id}:{membership.grace_expires_at.isoformat()}:{boundary}",
            telegram_id=membership.telegram_id,
            kind="group_grace_reminder",
            message=(
                f"必需群组宽限期不足 {boundary} 小时。请尽快重新加入群组，"
                "否则媒体账号会自动停用；重新加入后会自动恢复。"
            ),
        )
    due = session.exec(
        select(TelegramGroupMembership).where(
            TelegramGroupMembership.status == "grace",
            TelegramGroupMembership.grace_expires_at.is_not(None),
            TelegramGroupMembership.grace_expires_at <= now,
        )
    ).all()
    disabled = 0
    failed = 0
    for membership in due:
        user = session.get(PortalUser, membership.portal_user_id)
        if user is None or user.role in {"admin", "root"}:
            membership.status = "member"
            session.add(membership)
            continue
        if not is_group_policy_applicable(
            user,
            {
                "groupMembershipEnabled": True,
                "groupPolicyScope": "new_users_only",
            },
        ):
            membership.status = "exempt"
            membership.grace_expires_at = None
            membership.disabled_at = None
            membership.updated_at = now
            session.add(membership)
            continue
        if user.status != "deleted":
            was_active = desired_account_status(session, user, now=now) == "active"
            set_account_hold(
                session,
                user,
                kind="group",
                actor="worker",
                source="group_membership",
                metadata={"groupId": membership.group_id},
                now=now,
            )
            if was_active:
                disabled += 1
            if user.abs_user_id:
                try:
                    await abs_client.update_user(user.abs_user_id, {"isActive": False})
                except Exception:  # noqa: BLE001 - isolate one membership failure
                    failed += 1
                    enqueue_reconciliation_job(
                        session,
                        idempotency_key=f"group-disable:{membership.id}",
                        operation="set_active",
                        target_type="portal_user",
                        target_id=user.id,
                        abs_user_id=user.abs_user_id,
                        payload={"isActive": False, "source": "group_membership"},
                    )
        membership.status = "disabled"
        membership.disabled_at = now
        membership.updated_at = now
        session.add(membership)
        session.add(
            AuditLog(
                actor_username="worker",
                action="telegram.group.disable_after_grace",
                target_type="portal_user",
                target_id=user.id,
            )
        )
        if user.telegram_id:
            enqueue_notification(
                session,
                dedupe_key=f"group-disabled:{membership.id}",
                telegram_id=user.telegram_id,
                kind="group_disabled",
                message="必需群组宽限期已结束，媒体账号已停用。重新加入群组后可自动恢复。",
            )
    session.commit()
    return {"checked": len(due), "disabled": disabled, "failed": failed}
