"""Track unfinished backup cycles and expand versioned admission coverage.

Revision ID: 20260917_0048
Revises: 20260917_0047

Only a valid legacy authority advances to schema 2. Closed operation ownership is
preserved, while the generation advances to invalidate earlier receipts and CAS.
Missing, malformed, unknown, and already-upgraded authority records are retained.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from alembic import op
import sqlalchemy as sa

revision = "20260917_0048"
down_revision = "20260917_0047"
branch_labels = None
depends_on = None

_TABLE = "host_maintenance_work_cycles"
_SEED_UPGRADE_OPERATION = "f96750f5-e078-48f2-858d-1fdf82acf270"
_PAYLOAD_KEYS = {
    "schema_version", "scope", "generation", "operation_id", "reason",
    "changed_at", "full_host_closure",
}
_COLUMNS = {
    "id", "resource_id", "consumer", "worker_incarnation", "admitted_generation",
    "ownership_nonce", "state", "phase", "job_id", "started_at", "heartbeat_at",
    "lease_expires_at", "unresolved_reason",
}
_CHECKS = {
    "ck_host_cycle_consumer", "ck_host_cycle_generation", "ck_host_cycle_state",
    "ck_host_cycle_deadline", "ck_host_cycle_unresolved_reason",
}


def _create_registry(bind) -> None:
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("resource_id", sa.String(length=160), nullable=False),
            sa.Column("consumer", sa.String(length=80), nullable=False),
            sa.Column("worker_incarnation", sa.String(length=36), nullable=False),
            sa.Column("admitted_generation", sa.Integer(), nullable=False),
            sa.Column("ownership_nonce", sa.String(length=36), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("phase", sa.String(length=80), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("unresolved_reason", sa.String(length=160), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint("consumer = 'backup_cycles'", name="ck_host_cycle_consumer"),
            sa.CheckConstraint("admitted_generation > 0", name="ck_host_cycle_generation"),
            sa.CheckConstraint("state IN ('active', 'unresolved')", name="ck_host_cycle_state"),
            sa.CheckConstraint(
                "lease_expires_at >= heartbeat_at", name="ck_host_cycle_deadline"
            ),
            sa.CheckConstraint(
                "(state = 'active' AND unresolved_reason IS NULL) OR "
                "(state = 'unresolved' AND unresolved_reason IS NOT NULL)",
                name="ck_host_cycle_unresolved_reason",
            ),
        )
    else:
        # A retained table may be encountered after downgrade/re-upgrade. Never
        # replace it or discard unfinished ownership to make migration succeed.
        columns = inspector.get_columns(_TABLE)
        if {column["name"] for column in columns} != _COLUMNS:
            raise RuntimeError("Existing backup cycle registry columns are incompatible")
        if inspector.get_pk_constraint(_TABLE).get("constrained_columns") != ["id"]:
            raise RuntimeError("Existing backup cycle registry identity is incompatible")
        checks = {check["name"] for check in inspector.get_check_constraints(_TABLE)}
        if not _CHECKS.issubset(checks):
            raise RuntimeError("Existing backup cycle registry constraints are incomplete")

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(_TABLE)}
    if "ix_host_cycle_resource_consumer_state" not in indexes:
        op.create_index(
            "ix_host_cycle_resource_consumer_state",
            _TABLE,
            ["resource_id", "consumer", "state", "lease_expires_at"],
        )


def _valid_legacy(row) -> bool:
    # Frozen schema-1 validator: do not import future mutable application code.
    payload = row["payload"]
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        return False
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["scope"] != "project_execution"
        or payload["full_host_closure"] is not False
        or type(payload["generation"]) is not int
        or payload["generation"] < 1
        or type(row["version"]) is not int
        or payload["generation"] != row["version"]
        or row["status"] not in ("open", "closed")
        or type(row["enabled"]) is not bool
        or row["enabled"] != (row["status"] == "open")
        or not isinstance(payload["reason"], str)
        or not payload["reason"].strip()
        or len(payload["reason"]) > 500
        or "\x00" in payload["reason"]
    ):
        return False
    if payload["generation"] == 1:
        return (
            row["status"] == "open"
            and payload["operation_id"] is None
            and payload["changed_at"] is None
            and payload["reason"] == "migration-seed"
        )
    operation_id = payload["operation_id"]
    changed_at = payload["changed_at"]
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
        raise RuntimeError("Backup cycle admission requires PostgreSQL")
    _create_registry(bind)
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
    bind.execute(sa.text("SELECT set_config('lock_timeout', '5s', true)"))
    row = bind.execute(
        sa.select(records)
        .where(
            records.c.domain == "host-maintenance-admission",
            records.c.resource_id == "runtime-node",
        )
        .with_for_update()
    ).mappings().one_or_none()
    if row is None or not _valid_legacy(row):
        return

    now = bind.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    payload = dict(row["payload"])
    payload.update(
        schema_version=2,
        scope="project_execution+backup_cycles",
        generation=row["version"] + 1,
    )
    if row["version"] == 1:
        payload.update(
            operation_id=_SEED_UPGRADE_OPERATION,
            reason="backup-cycle-coverage-migration",
            changed_at=now.isoformat(),
        )
    changed = bind.execute(
        sa.update(records)
        .where(records.c.id == row["id"], records.c.version == row["version"])
        .values(payload=payload, version=payload["generation"], updated_at=now)
        .returning(records.c.id)
    ).scalar_one_or_none()
    if changed != row["id"]:
        raise RuntimeError("Maintenance coverage migration lost its authority generation")


def downgrade() -> None:
    # Retain advanced authority and unfinished cycles. Dropping and recreating
    # an empty registry would erase unresolved work and manufacture a clear
    # observation; rewriting authority could reopen or revive an old receipt.
    pass
