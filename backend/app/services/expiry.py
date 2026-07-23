from datetime import UTC
from typing import Protocol

import httpx
from sqlmodel import Session, select

from app.models import PortalUser, utcnow


class AbsUserUpdater(Protocol):
    async def update_user(self, user_id: str, payload: dict): ...


def _aware(expires_at):
    if expires_at is not None and expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=UTC)
    return expires_at


async def disable_upstream_if_expired(user: PortalUser, session: Session, abs_factory) -> bool:
    """Immediately revoke a user's upstream media access the moment they are
    found to be past their expiry, instead of waiting for the next background
    worker tick.

    Called from the portal access paths (login, /api/me) so a naturally expired
    member loses direct media-app playback as soon as they touch the portal.
    Admins are never affected; disabled/deleted accounts are admin-controlled
    and handled elsewhere. Returns True if an upstream disable was issued.
    """
    if user.role in {"admin", "root"}:
        return False
    if user.status == "pending" and user.telegram_binding_required and not user.telegram_id:
        return False
    expires_at = _aware(user.expires_at)
    if expires_at is None or expires_at > utcnow():
        return False
    # User is past expiry: mark local status (idempotent) ...
    if user.status not in ("expired", "disabled", "deleted"):
        user.status = "expired"
        user.session_version = int(user.session_version or 0) + 1
        user.updated_at = utcnow()
        session.add(user)
        session.commit()
    # ... and push isActive=False upstream right now.
    if not user.abs_user_id:
        return False
    try:
        async with abs_factory() as abs_client:
            await abs_client.update_user(user.abs_user_id, {"isActive": False})
    except (httpx.HTTPError, TypeError, RuntimeError):
        return False
    return True


async def sync_expired_users(session: Session, abs_client: AbsUserUpdater) -> dict[str, int]:
    now = utcnow()
    # Include users already marked "expired" so the worker keeps reconciling the
    # upstream account. The login gate / set_expiry may flip status to "expired"
    # before this worker runs; if we only looked at "active" we would never push
    # isActive=False upstream and the user would keep direct media-app access.
    candidates = session.exec(
        select(PortalUser).where(
            PortalUser.status.in_(["active", "expired"]),  # noqa: E711
            PortalUser.expires_at != None,  # noqa: E711
            PortalUser.role.notin_(["admin", "root"]),
            PortalUser.abs_user_id != None,  # noqa: E711 — nothing to push upstream
        )
    ).all()
    disabled = 0
    failed = 0
    for user in candidates:
        expires_at = user.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at is not None and expires_at <= now:
            # Per-user fault isolation: a single upstream failure (e.g. the ABS
            # account was deleted -> 404) must NOT crash the whole worker run and
            # leave every other expired user un-reconciled.
            try:
                await abs_client.update_user(user.abs_user_id, {"isActive": False})
            except Exception:  # noqa: BLE001 — isolate one bad user from the batch
                failed += 1
                # Still mark the portal status so the login gate stays correct.
                if user.status != "expired":
                    user.status = "expired"
                    user.session_version = int(user.session_version or 0) + 1
                    session.add(user)
                continue
            if user.status != "expired":
                user.status = "expired"
                user.session_version = int(user.session_version or 0) + 1
                session.add(user)
            disabled += 1
    session.commit()
    return {"disabled": disabled, "failed": failed}
