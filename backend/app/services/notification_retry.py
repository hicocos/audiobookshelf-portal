from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import and_, or_, update
from sqlmodel import Session

from app.models import AuditLog, TelegramNotification, utcnow


class NotificationRetryError(ValueError):
    pass


def retry_notification_safely(
    session: Session,
    notification_id: str,
    *,
    actor: str,
    expected_version: int,
    stale_after_minutes: int = 5,
) -> TelegramNotification:
    item = session.get(TelegramNotification, notification_id)
    if item is None:
        raise NotificationRetryError("notification not found")
    original_status = item.status
    original_version = int(item.version or 0)
    now = utcnow()
    stale_before = now - timedelta(minutes=max(1, stale_after_minutes))
    result = session.exec(
        update(TelegramNotification)
        .where(
            TelegramNotification.id == notification_id,
            TelegramNotification.version == expected_version,
            or_(
                TelegramNotification.status.in_(["failed", "retry"]),
                and_(
                    TelegramNotification.status == "sending",
                    TelegramNotification.claimed_at.is_not(None),
                    TelegramNotification.claimed_at < stale_before,
                ),
            ),
        )
        .values(
            status="retry",
            version=TelegramNotification.version + 1,
            next_attempt_at=now,
            claimed_at=None,
            last_error=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.expire_all()
        current = session.get(TelegramNotification, notification_id)
        if current is None:
            raise NotificationRetryError("notification not found")
        if int(current.version or 0) != expected_version:
            raise NotificationRetryError("notification version changed")
        if current.status == "sending":
            raise NotificationRetryError("notification is actively sending")
        raise NotificationRetryError("notification status is not retryable")
    session.add(
        AuditLog(
            actor_username=actor,
            action="admin.telegram_notification.retry",
            target_type="telegram_notification",
            target_id=notification_id,
            detail_json=json.dumps(
                {
                    "fromStatus": original_status,
                    "fromVersion": original_version,
                    "reason": (
                        "stale_claim_recovery"
                        if original_status == "sending"
                        else "manual_retry"
                    ),
                },
                ensure_ascii=False,
            ),
        )
    )
    session.commit()
    retried = session.get(TelegramNotification, notification_id)
    if retried is None:  # pragma: no cover - guarded by the successful update
        raise NotificationRetryError("notification not found")
    return retried
