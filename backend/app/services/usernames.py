from sqlmodel import Session, select

from app.models import PortalUser, normalize_username, utcnow


def find_username_owner(session: Session, username: str) -> PortalUser | None:
    """Return the current or deleted identity that owns a username."""

    return session.exec(
        select(PortalUser).where(
            PortalUser.username_normalized == normalize_username(username)
        )
    ).first()


def archive_deleted_username(session: Session, user: PortalUser) -> None:
    """Release a deleted username without reviving or overwriting its identity."""

    if user.status != "deleted":
        raise ValueError("only deleted usernames can be archived")

    tombstone = f"__deleted__:{user.id}"
    user.username = tombstone
    user.abs_username = tombstone
    user.updated_at = utcnow()
    session.add(user)
    # Free both case-insensitive unique indexes before the replacement identity
    # is inserted in the same transaction.
    session.flush()
