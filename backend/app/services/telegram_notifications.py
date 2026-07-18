import math
from datetime import UTC, datetime, timedelta
from typing import Any
from sqlalchemy import update
from sqlmodel import Session, select

from app.models import PortalUser, TelegramNotification, utcnow


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def enqueue_notification(
    session: Session,
    *,
    dedupe_key: str,
    telegram_id: str,
    kind: str,
    message: str,
) -> bool:
    existing = session.exec(
        select(TelegramNotification).where(
            TelegramNotification.dedupe_key == dedupe_key
        )
    ).first()
    if existing is not None:
        return False
    session.add(
        TelegramNotification(
            dedupe_key=dedupe_key,
            telegram_id=str(telegram_id),
            kind=kind,
            message=message,
        )
    )
    session.commit()
    return True


def enqueue_lifecycle_notifications(
    session: Session,
    *,
    public_settings: dict[str, Any],
) -> dict[str, int]:
    telegram = public_settings.get("telegram")
    telegram = telegram if isinstance(telegram, dict) else {}
    if not bool(telegram.get("lifecycleNotificationsEnabled", True)):
        return {"expiryQueued": 0}

    reminder_days = {
        int(day)
        for day in telegram.get("expiryReminderDays", [7, 3, 1, 0])
        if isinstance(day, int) and 0 <= day <= 365
    }
    now = utcnow()
    users = session.exec(
        select(PortalUser).where(
            PortalUser.telegram_id.is_not(None),
            PortalUser.status.in_(["active", "expired"]),
            PortalUser.role.notin_(["admin", "root"]),
        )
    ).all()
    expiry_queued = 0
    for user in users:
        expiry = _aware(user.expires_at)
        if expiry is None or not user.telegram_id:
            continue
        seconds_left = (expiry - now).total_seconds()
        expiry_key = expiry.isoformat()
        if seconds_left < 0:
            queued = enqueue_notification(
                session,
                dedupe_key=f"expired:{user.id}:{expiry_key}",
                telegram_id=user.telegram_id,
                kind="expired",
                message=(
                    f"账号 {user.username} 已到期，媒体访问已暂停。\n\n"
                    "请打开 Bot 用户面板，使用续期码恢复账号。"
                ),
            )
        else:
            # Round up so a D-7 reminder is still emitted when the worker runs
            # a few minutes after the exact seven-day boundary.
            days_left = max(0, math.ceil(seconds_left / 86400))
            if days_left not in reminder_days:
                continue
            queued = enqueue_notification(
                session,
                dedupe_key=f"expiry-reminder:{user.id}:{expiry_key}:{days_left}",
                telegram_id=user.telegram_id,
                kind="expiry_reminder",
                message=(
                    f"账号 {user.username} 将在 {days_left} 天内到期。\n\n"
                    "建议提前使用续期码，避免听书客户端中断。"
                ),
            )
        expiry_queued += int(queued)

    return {"expiryQueued": expiry_queued}


def claim_notifications(session: Session, *, limit: int = 10) -> list[TelegramNotification]:
    now = utcnow()
    stale = now - timedelta(minutes=5)
    session.exec(
        update(TelegramNotification)
        .where(
            TelegramNotification.status == "sending",
            TelegramNotification.claimed_at.is_not(None),
            TelegramNotification.claimed_at <= stale,
        )
        .values(status="retry", next_attempt_at=now, updated_at=now)
    )
    candidate_ids = session.exec(
        select(TelegramNotification.id)
        .where(
            TelegramNotification.status.in_(["pending", "retry"]),
            TelegramNotification.next_attempt_at <= now,
        )
        .order_by(TelegramNotification.created_at)
        .limit(max(1, min(limit, 50)))
    ).all()
    claimed_ids: list[str] = []
    for notification_id in candidate_ids:
        result = session.exec(
            update(TelegramNotification)
            .where(
                TelegramNotification.id == notification_id,
                TelegramNotification.status.in_(["pending", "retry"]),
                TelegramNotification.next_attempt_at <= now,
            )
            .values(status="sending", claimed_at=now, updated_at=now)
        )
        if result.rowcount == 1:
            claimed_ids.append(notification_id)
    session.commit()
    return [
        item
        for notification_id in claimed_ids
        if (item := session.get(TelegramNotification, notification_id)) is not None
    ]


def acknowledge_notification(
    session: Session,
    notification: TelegramNotification,
    *,
    success: bool,
    error: str | None = None,
    retry_after_seconds: int | None = None,
    retryable: bool = True,
) -> TelegramNotification:
    now = utcnow()
    notification.attempts += 1
    notification.updated_at = now
    if success:
        notification.status = "sent"
        notification.sent_at = now
        notification.last_error = None
    else:
        notification.status = (
            "retry" if retryable and notification.attempts < 10 else "failed"
        )
        notification.last_error = (error or "telegram delivery failed")[:1000]
        delay = retry_after_seconds or min(3600, 5 * (2 ** min(notification.attempts - 1, 9)))
        notification.next_attempt_at = now + timedelta(seconds=max(1, int(delay)))
    session.add(notification)
    session.commit()
    session.refresh(notification)
    return notification
