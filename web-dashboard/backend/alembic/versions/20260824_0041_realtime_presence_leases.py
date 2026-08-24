"""Add durable realtime presence leases and fencing.

Revision ID: 20260824_0041
Revises: 20260824_0040
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0041"
down_revision: str | None = "20260824_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "realtime_participants" not in set(inspector.get_table_names()):
        raise RuntimeError("Realtime presence migration requires realtime_participants")

    columns = {column["name"] for column in inspector.get_columns("realtime_participants")}
    if "presence_fencing_token" not in columns:
        op.add_column(
            "realtime_participants",
            sa.Column(
                "presence_fencing_token",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
        )
    if "presence_lease_expires_at" not in columns:
        op.add_column(
            "realtime_participants",
            sa.Column("presence_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        )

    inspector = sa.inspect(bind)
    checks = {
        item.get("name")
        for item in inspector.get_check_constraints("realtime_participants")
        if item.get("name")
    }
    if "ck_realtime_participant_presence_fencing_token" not in checks:
        op.create_check_constraint(
            "ck_realtime_participant_presence_fencing_token",
            "realtime_participants",
            "presence_fencing_token >= 0",
        )

    inspector = sa.inspect(bind)
    indexes = {
        item.get("name")
        for item in inspector.get_indexes("realtime_participants")
        if item.get("name")
    }
    if "ix_realtime_participants_presence_lease_expires_at" not in indexes:
        op.create_index(
            "ix_realtime_participants_presence_lease_expires_at",
            "realtime_participants",
            ["presence_lease_expires_at"],
        )
    if "ix_realtime_participants_presence_lease" not in indexes:
        op.create_index(
            "ix_realtime_participants_presence_lease",
            "realtime_participants",
            ["organization_id", "status", "presence_lease_expires_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "realtime_participants" not in set(inspector.get_table_names()):
        return

    indexes = {
        item.get("name")
        for item in inspector.get_indexes("realtime_participants")
        if item.get("name")
    }
    for name in (
        "ix_realtime_participants_presence_lease",
        "ix_realtime_participants_presence_lease_expires_at",
    ):
        if name in indexes:
            op.drop_index(name, table_name="realtime_participants")

    inspector = sa.inspect(bind)
    checks = {
        item.get("name")
        for item in inspector.get_check_constraints("realtime_participants")
        if item.get("name")
    }
    if "ck_realtime_participant_presence_fencing_token" in checks:
        op.drop_constraint(
            "ck_realtime_participant_presence_fencing_token",
            "realtime_participants",
            type_="check",
        )

    columns = {column["name"] for column in sa.inspect(bind).get_columns("realtime_participants")}
    if "presence_lease_expires_at" in columns:
        op.drop_column("realtime_participants", "presence_lease_expires_at")
    if "presence_fencing_token" in columns:
        op.drop_column("realtime_participants", "presence_fencing_token")
