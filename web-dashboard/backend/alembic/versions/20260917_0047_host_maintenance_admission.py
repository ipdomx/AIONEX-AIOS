"""Seed the project execution maintenance admission authority.

Revision ID: 20260917_0047
Revises: 20260908_0046

The singleton is explicitly open for this first project-execution-only consumer.
It is never lazily created by an admission check. Replaying this data migration
preserves existing state, including an in-progress closed maintenance operation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

revision = "20260917_0047"
down_revision = "20260908_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Maintenance admission requires PostgreSQL")

    records = sa.table(
        "owner_control_records",
        sa.column("id", sa.String(length=36)),
        sa.column("domain", sa.String(length=80)),
        sa.column("resource_id", sa.String(length=160)),
        sa.column("status", sa.String(length=32)),
        sa.column("enabled", sa.Boolean()),
        sa.column("payload", sa.JSON()),
        sa.column("version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.execute(
        insert(records)
        .values(
            id="72490f9b-08f7-4f03-986a-a1a71ddbf74b",
            domain="host-maintenance-admission",
            resource_id="runtime-node",
            status="open",
            enabled=True,
            version=1,
            payload={
                "schema_version": 1,
                "scope": "project_execution",
                "generation": 1,
                "operation_id": None,
                "reason": "migration-seed",
                "changed_at": None,
                "full_host_closure": False,
            },
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["domain", "resource_id"])
    )


def downgrade() -> None:
    # This data-only revision retains its durable authority. Deleting a closed
    # row would let a later upgrade replace that operation with an open seed.
    # Older code ignores this separate domain; re-upgrade must preserve it.
    pass
