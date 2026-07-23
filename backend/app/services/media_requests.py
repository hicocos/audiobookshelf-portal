from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import MediaRequest, utcnow


class MediaRequestLimitError(ValueError):
    pass


def create_open_media_request(
    session: Session,
    *,
    portal_user_id: str,
    title: str,
    details: str | None,
) -> MediaRequest:
    used_slots = set(
        session.exec(
            select(MediaRequest.open_slot).where(
                MediaRequest.portal_user_id == portal_user_id,
                MediaRequest.status.in_(["pending", "accepted"]),
                MediaRequest.open_slot.is_not(None),
            )
        ).all()
    )
    slot = next((value for value in range(1, 4) if value not in used_slots), None)
    if slot is None:
        raise MediaRequestLimitError("最多同时保留 3 个待处理工单。")
    item = MediaRequest(
        portal_user_id=portal_user_id,
        # Keep the legacy column for existing data/API compatibility. New
        # tickets all belong to the single audiobook request flow.
        kind="book",
        title=title.strip(),
        details=(details or "").strip() or None,
        open_slot=slot,
    )
    session.add(item)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # A concurrent request took the same slot. Refusing this request keeps
        # the hard three-item invariant; the caller can safely retry.
        raise MediaRequestLimitError("工单正在并发提交，请重试。") from exc
    session.refresh(item)
    return item


def apply_media_request_status(item: MediaRequest, status: str) -> None:
    if item.status not in {"pending", "accepted"} and status in {"pending", "accepted"}:
        raise MediaRequestLimitError("已关闭工单不能重新打开，请创建新工单。")
    item.status = status
    if status not in {"pending", "accepted"}:
        item.open_slot = None


def cancel_media_request(item: MediaRequest) -> None:
    if item.status not in {"pending", "accepted"}:
        raise MediaRequestLimitError("只有待处理或已受理的请求可以撤销。")
    item.status = "cancelled"
    item.open_slot = None
    item.updated_at = utcnow()
    item.resolved_at = item.updated_at


def transition_open_media_request(
    session: Session,
    *,
    request_id: str,
    status: str,
    admin_note: str | None = None,
    handled_by_user_id: str | None = None,
) -> MediaRequest:
    """Atomically transition an open request so stale writers cannot reopen it."""
    now = utcnow()
    values: dict[str, object] = {"status": status, "updated_at": now}
    if status not in {"pending", "accepted"}:
        values.update(open_slot=None, resolved_at=now)
    if admin_note is not None:
        values["admin_note"] = admin_note
    if handled_by_user_id is not None:
        values["handled_by_user_id"] = handled_by_user_id
    result = session.exec(
        update(MediaRequest)
        .where(
            MediaRequest.id == request_id,
            MediaRequest.status.in_(["pending", "accepted"]),
        )
        .values(**values)
    )
    if result.rowcount != 1:
        session.rollback()
        raise MediaRequestLimitError("工单状态已变化，请刷新后重试。")
    session.flush()
    session.expire_all()
    item = session.get(MediaRequest, request_id)
    if item is None:
        raise MediaRequestLimitError("工单不存在。")
    return item
