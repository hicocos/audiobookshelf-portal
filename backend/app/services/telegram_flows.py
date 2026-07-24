import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, select

from app.config import Settings
from app.models import TelegramFlowSession, utcnow


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def flow_payload(flow: TelegramFlowSession) -> dict[str, Any]:
    try:
        value = json.loads(flow.payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def get_flow(
    session: Session,
    telegram_id: str,
    *,
    kind: str | None = None,
) -> TelegramFlowSession | None:
    flow = session.exec(
        select(TelegramFlowSession).where(
            TelegramFlowSession.telegram_id == str(telegram_id).strip()
        )
    ).first()
    if flow is None:
        return None
    if _aware(flow.expires_at) <= utcnow():
        session.delete(flow)
        session.commit()
        return None
    if kind is not None and flow.kind != kind:
        return None
    return flow


def flow_state(session: Session, telegram_id: str) -> tuple[TelegramFlowSession | None, str]:
    flow = session.exec(
        select(TelegramFlowSession).where(
            TelegramFlowSession.telegram_id == str(telegram_id).strip()
        )
    ).first()
    if flow is None:
        return None, "missing"
    if flow.step == "completed":
        return flow, "completed"
    if _aware(flow.expires_at) <= utcnow():
        session.delete(flow)
        session.commit()
        return None, "expired"
    return flow, "active"


def save_flow(
    session: Session,
    *,
    telegram_id: str,
    kind: str,
    step: str,
    payload: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> TelegramFlowSession:
    settings = settings or Settings()
    normalized_id = str(telegram_id).strip()
    now = utcnow()
    ttl = max(1, int(settings.telegram_flow_ttl_minutes))
    flow = session.exec(
        select(TelegramFlowSession).where(
            TelegramFlowSession.telegram_id == normalized_id
        )
    ).first()
    encoded = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
    if flow is None:
        flow = TelegramFlowSession(
            telegram_id=normalized_id,
            kind=kind,
            step=step,
            payload_json=encoded,
            expires_at=now + timedelta(minutes=ttl),
        )
    else:
        flow.kind = kind
        flow.step = step
        flow.payload_json = encoded
        flow.expires_at = now + timedelta(minutes=ttl)
        flow.updated_at = now
    session.add(flow)
    session.commit()
    session.refresh(flow)
    return flow


def clear_flow(session: Session, telegram_id: str) -> bool:
    flow = session.exec(
        select(TelegramFlowSession).where(
            TelegramFlowSession.telegram_id == str(telegram_id).strip()
        )
    ).first()
    if flow is None:
        return False
    session.delete(flow)
    session.commit()
    return True


def complete_flow(session: Session, telegram_id: str) -> bool:
    flow = session.exec(
        select(TelegramFlowSession).where(
            TelegramFlowSession.telegram_id == str(telegram_id).strip()
        )
    ).first()
    if flow is None:
        return False
    flow.step = "completed"
    flow.payload_json = "{}"
    flow.updated_at = utcnow()
    session.add(flow)
    session.commit()
    return True


def transition_flow_step(
    session: Session,
    *,
    flow_id: str,
    expected_step: str,
    next_step: str,
) -> bool:
    """Atomically claim a confirmation flow before executing side effects."""
    result = session.exec(
        update(TelegramFlowSession)
        .where(
            TelegramFlowSession.id == flow_id,
            TelegramFlowSession.step == expected_step,
        )
        .values(step=next_step, updated_at=utcnow())
    )
    session.commit()
    return result.rowcount == 1


def public_flow(
    flow: TelegramFlowSession | None, *, phase: str | None = None
) -> dict[str, Any]:
    if flow is None:
        return {"active": False, **({"phase": phase} if phase else {})}
    if phase == "completed" or flow.step == "completed":
        return {"active": False, "phase": "completed"}
    payload = flow_payload(flow)
    return {
        "active": True,
        "id": flow.id,
        "kind": flow.kind,
        "step": flow.step,
        "username": payload.get("username"),
        "expiresAt": _aware(flow.expires_at).isoformat(),
    }
