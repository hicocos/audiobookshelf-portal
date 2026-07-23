"""Enforce the per-user open media request limit under concurrency."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0004"
down_revision: str | Sequence[str] | None = "20260717_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media_requests", sa.Column("open_slot", sa.Integer(), nullable=True))
    connection = op.get_bind()
    overflow = connection.execute(
        sa.text(
            "SELECT portal_user_id, COUNT(*) AS count FROM media_requests "
            "WHERE status IN ('pending', 'accepted') "
            "GROUP BY portal_user_id HAVING COUNT(*) > 3"
        )
    ).first()
    if overflow is not None:
        raise RuntimeError(
            "Cannot enforce media request limit: a user has more than 3 open requests"
        )

    open_requests = connection.execute(
        sa.text(
            "SELECT id, portal_user_id FROM media_requests "
            "WHERE status IN ('pending', 'accepted') "
            "ORDER BY portal_user_id, created_at, id"
        )
    ).mappings()
    next_slot: dict[str, int] = {}
    for request in open_requests:
        user_id = str(request["portal_user_id"])
        slot = next_slot.get(user_id, 1)
        connection.execute(
            sa.text("UPDATE media_requests SET open_slot = :slot WHERE id = :id"),
            {"slot": slot, "id": request["id"]},
        )
        next_slot[user_id] = slot + 1

    op.create_index(
        "ux_media_requests_user_open_slot",
        "media_requests",
        ["portal_user_id", "open_slot"],
        unique=True,
        sqlite_where=sa.text("open_slot IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_media_requests_user_open_slot", table_name="media_requests")
    op.drop_column("media_requests", "open_slot")
