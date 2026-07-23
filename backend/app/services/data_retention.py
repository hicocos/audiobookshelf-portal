from datetime import timedelta

from sqlalchemy import delete
from sqlmodel import Session

from app.models import (
    PasswordResetToken,
    TelegramBindToken,
    TelegramFlowSession,
    TelegramNotification,
    utcnow,
)


def apply_data_retention(session: Session) -> dict[str, int]:
    """Remove short-lived secrets and operational messages on documented schedules."""

    now = utcnow()
    token_cutoff = now - timedelta(days=7)
    flow_cutoff = now - timedelta(days=1)
    notification_cutoff = now - timedelta(days=180)
    statements = {
        "passwordResetTokensDeleted": delete(PasswordResetToken).where(
            PasswordResetToken.expires_at < token_cutoff
        ),
        "telegramBindTokensDeleted": delete(TelegramBindToken).where(
            TelegramBindToken.expires_at < token_cutoff
        ),
        "telegramFlowsDeleted": delete(TelegramFlowSession).where(
            TelegramFlowSession.expires_at < flow_cutoff
        ),
        "terminalNotificationsDeleted": delete(TelegramNotification).where(
            TelegramNotification.status.in_(["sent", "failed"]),
            TelegramNotification.updated_at < notification_cutoff,
        ),
    }
    result: dict[str, int] = {}
    for key, statement in statements.items():
        execution = session.exec(statement)
        result[key] = max(0, int(execution.rowcount or 0))
    session.commit()
    return result
