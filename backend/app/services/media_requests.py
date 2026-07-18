from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import MediaRequest


class MediaRequestLimitError(ValueError):
    pass


def create_open_media_request(
    session: Session,
    *,
    portal_user_id: str,
    kind: Literal["book", "podcast"],
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
        kind=kind,
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
    item.status = status
    if status not in {"pending", "accepted"}:
        item.open_slot = None
