"""Add request-only Security Lab admission without claiming execution coverage.

Revision ID: 20260917_0052
Revises: 20260917_0051

Only a validated schema-5 authority advances. Preserve closure, operation, reason
and control timestamp, advance the generation, and retain malformed/legacy rows.
There are no queue changes, worker activation, remote calls or drain assertions.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from alembic import op
import sqlalchemy as sa

revision = "20260917_0052"
down_revision = "20260917_0051"
branch_labels = None
depends_on = None

_PAYLOAD_KEYS = {
    "schema_version", "scope", "generation", "operation_id", "reason",
    "changed_at", "full_host_closure",
}


def _valid_schema_five(row) -> bool:
    # Frozen validation: do not import mutable future application validators.
    payload = row["payload"]
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        return False
    if (
        type(payload["schema_version"]) is not int or payload["schema_version"] != 5
        or payload["scope"] != "project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch+security_remediation_preparation"
        or payload["full_host_closure"] is not False
        or type(payload["generation"]) is not int or payload["generation"] < 5
        or type(row["version"]) is not int
        or payload["generation"] != row["version"]
        or row["status"] not in ("open", "closed")
        or type(row["enabled"]) is not bool
        or row["enabled"] != (row["status"] == "open")
        or not isinstance(payload["reason"], str) or not payload["reason"].strip()
        or len(payload["reason"]) > 500 or "\x00" in payload["reason"]
    ):
        return False
    operation_id, changed_at = payload["operation_id"], payload["changed_at"]
    if not isinstance(operation_id, str) or not isinstance(changed_at, str):
        return False
    try:
        return (
            str(UUID(operation_id)) == operation_id
            and datetime.fromisoformat(changed_at).utcoffset() is not None
        )
    except ValueError:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Security scan request admission requires PostgreSQL")
    bind.execute(sa.text("SELECT set_config('lock_timeout', '5s', true)"))
    records = sa.table(
        "owner_control_records",
        sa.column("id", sa.String(length=36)),
        sa.column("domain", sa.String(length=80)),
        sa.column("resource_id", sa.String(length=160)),
        sa.column("status", sa.String(length=32)),
        sa.column("enabled", sa.Boolean()),
        sa.column("payload", sa.JSON()),
        sa.column("version", sa.Integer()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    row = bind.execute(
        sa.select(records).where(
            records.c.domain == "host-maintenance-admission",
            records.c.resource_id == "runtime-node",
        ).with_for_update()
    ).mappings().one_or_none()
    if row is None or not _valid_schema_five(row):
        return
    payload = dict(row["payload"])
    payload.update(
        schema_version=6,
        scope=(
            "project_execution+backup_cycles+academy_course_packages+"
            "notification_delivery_dispatch+security_remediation_preparation+"
            "security_scan_requests"
        ),
        generation=row["version"] + 1,
    )
    changed = bind.execute(
        sa.update(records)
        .where(records.c.id == row["id"], records.c.version == row["version"])
        .values(
            payload=payload, version=payload["generation"],
            updated_at=bind.execute(sa.select(sa.func.clock_timestamp())).scalar_one(),
        ).returning(records.c.id)
    ).scalar_one_or_none()
    if changed != row["id"]:
        raise RuntimeError("Scan request admission migration lost authority generation")


def downgrade() -> None:
    # Keep the widened authority and every queued/unfinished record. Older code
    # fails closed on unsupported scope instead of reopening or erasing evidence.
    pass
