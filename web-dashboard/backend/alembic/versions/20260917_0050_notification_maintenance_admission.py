"""Expand partial admission and unfinished ownership to owned external notification dispatch.

Revision ID: 20260917_0050
Revises: 20260917_0049

Only a valid schema-3 authority advances to schema 4. Existing operation identity,
closed/open state and control timestamps remain unchanged; generation advances.
Downgrade retains authority and unfinished activity instead of manufacturing an
empty registry or reviving an old control receipt.
"""

from __future__ import annotations

from datetime import datetime
import re
from uuid import UUID

from alembic import op
import sqlalchemy as sa

revision = "20260917_0050"
down_revision = "20260917_0049"
branch_labels = None
depends_on = None

_TABLE = "host_maintenance_work_cycles"
_COLUMNS = {
    "id", "resource_id", "consumer", "worker_incarnation", "admitted_generation",
    "ownership_nonce", "state", "phase", "job_id", "started_at", "heartbeat_at",
    "lease_expires_at", "unresolved_reason",
}
_CHECKS = {
    "ck_host_cycle_consumer", "ck_host_cycle_generation", "ck_host_cycle_state",
    "ck_host_cycle_deadline", "ck_host_cycle_unresolved_reason",
}
_PAYLOAD_KEYS = {
    "schema_version", "scope", "generation", "operation_id", "reason",
    "changed_at", "full_host_closure",
}


def _normalized_check(expression: str) -> str:
    # PostgreSQL renders varchar comparisons with casts and may represent IN
    # as = ANY(ARRAY[...]). Accept only the shipped equivalent definitions.
    value = re.sub(r"::(?:character varying|text)(?:\[\])?", "", expression.lower())
    return re.sub(r"[\s()]", "", value)


def _expand_registry(bind) -> None:
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        raise RuntimeError("Existing unfinished work registry is missing")
    if {column["name"] for column in inspector.get_columns(_TABLE)} != _COLUMNS:
        raise RuntimeError("Existing unfinished work registry columns are incompatible")
    if inspector.get_pk_constraint(_TABLE).get("constrained_columns") != ["id"]:
        raise RuntimeError("Existing unfinished work identity is incompatible")
    checks = {
        check["name"]: check["sqltext"]
        for check in inspector.get_check_constraints(_TABLE)
    }
    if not _CHECKS.issubset(checks):
        raise RuntimeError("Existing unfinished work constraints are incomplete")
    consumer_check = _normalized_check(checks["ck_host_cycle_consumer"])
    accepted_consumers = {
        "consumerin'backup_cycles','academy_course_packages'",
        "consumer=anyarray['backup_cycles','academy_course_packages']",
        "consumerin'backup_cycles','academy_course_packages','notification_delivery_dispatch'",
        "consumer=anyarray['backup_cycles','academy_course_packages','notification_delivery_dispatch']",
    }
    if consumer_check not in accepted_consumers:
        raise RuntimeError("Existing unfinished work consumer constraint is incompatible")
    op.drop_constraint("ck_host_cycle_consumer", _TABLE, type_="check")
    op.create_check_constraint(
        "ck_host_cycle_consumer", _TABLE,
        "consumer IN ('backup_cycles', 'academy_course_packages', 'notification_delivery_dispatch')",
    )

    academy_check = "ck_host_cycle_academy_job"
    if academy_check in checks:
        if _normalized_check(checks[academy_check]) != (
            "consumer<>'academy_course_packages'orjob_idisnotnull"
        ):
            raise RuntimeError("Existing academy activity reference is incompatible")
    else:
        op.create_check_constraint(
            academy_check, _TABLE,
            "consumer != 'academy_course_packages' OR job_id IS NOT NULL",
        )

    index_name = "uq_host_cycle_academy_package"
    indexes = {item["name"]: item for item in sa.inspect(bind).get_indexes(_TABLE)}
    if index_name in indexes:
        existing = indexes[index_name]
        predicate = existing.get("dialect_options", {}).get("postgresql_where", "")
        if (
            existing.get("unique") is not True
            or existing.get("column_names") != ["consumer", "job_id"]
            or _normalized_check(predicate) != "consumer='academy_course_packages'"
        ):
            raise RuntimeError("Existing academy activity uniqueness is incompatible")
    else:
        op.create_index(
            index_name, _TABLE, ["consumer", "job_id"], unique=True,
            postgresql_where=sa.text("consumer = 'academy_course_packages'"),
        )

    notification_check = "ck_host_cycle_notification_job"
    if notification_check in checks:
        if _normalized_check(checks[notification_check]) != (
            "consumer<>'notification_delivery_dispatch'orjob_idisnotnull"
        ):
            raise RuntimeError("Existing notification activity reference is incompatible")
    else:
        op.create_check_constraint(
            notification_check, _TABLE,
            "consumer != 'notification_delivery_dispatch' OR job_id IS NOT NULL",
        )
    notification_index = "uq_host_cycle_notification_delivery"
    indexes = {item["name"]: item for item in sa.inspect(bind).get_indexes(_TABLE)}
    if notification_index in indexes:
        existing = indexes[notification_index]
        predicate = existing.get("dialect_options", {}).get("postgresql_where", "")
        if (
            existing.get("unique") is not True
            or existing.get("column_names") != ["consumer", "job_id"]
            or _normalized_check(predicate) != "consumer='notification_delivery_dispatch'"
        ):
            raise RuntimeError("Existing notification activity uniqueness is incompatible")
    else:
        op.create_index(
            notification_index, _TABLE, ["consumer", "job_id"], unique=True,
            postgresql_where=sa.text("consumer = 'notification_delivery_dispatch'"),
        )


def _expand_attempts(bind) -> None:
    table = "notification_delivery_attempts"
    inspector = sa.inspect(bind)
    columns = {item["name"]: item for item in inspector.get_columns(table)}
    legacy = {
        "id", "delivery_id", "attempt_number", "status", "provider_message_id",
        "error_code", "response_metadata", "started_at", "completed_at",
    }
    proof_columns = {"dispatch_protocol_version", "dispatch_outcome"}
    if not legacy.issubset(columns) or set(columns) - legacy - proof_columns:
        raise RuntimeError("Existing notification attempt columns are incompatible")
    if inspector.get_pk_constraint(table).get("constrained_columns") != ["id"]:
        raise RuntimeError("Existing notification attempt identity is incompatible")
    unique = {
        item["name"]: item for item in inspector.get_unique_constraints(table)
    }.get("uq_notification_delivery_attempt")
    if unique is None or unique.get("column_names") != ["delivery_id", "attempt_number"]:
        raise RuntimeError("Existing notification attempt numbering uniqueness is incompatible")
    for name, data_type in (
        ("dispatch_protocol_version", sa.Integer()),
        ("dispatch_outcome", sa.String(length=32)),
    ):
        if name not in columns:
            op.add_column(table, sa.Column(name, data_type, nullable=True))
        else:
            column = columns[name]
            expected_type = sa.Integer if name == "dispatch_protocol_version" else sa.String
            if (
                not isinstance(column["type"], expected_type)
                or column.get("nullable") is not True
                or column.get("default") is not None
                or (name == "dispatch_outcome" and column["type"].length != 32)
            ):
                raise RuntimeError("Existing notification attempt proof column is incompatible")
    proof = (
        "(dispatch_protocol_version IS NULL AND dispatch_outcome IS NULL) OR "
        "(dispatch_protocol_version IS NOT NULL AND dispatch_protocol_version = 1 AND "
        "(dispatch_outcome IS NULL OR dispatch_outcome IN "
        "('accepted', 'no_send', 'rejected', 'uncertain')))"
    )
    checks = {
        item["name"]: item["sqltext"]
        for item in sa.inspect(bind).get_check_constraints(table)
    }
    name = "ck_notification_attempt_dispatch_proof"
    if name in checks:
        normalized = _normalized_check(checks[name])
        expected = _normalized_check(proof)
        array_rendering = expected.replace(
            "dispatch_outcomein'accepted','no_send','rejected','uncertain'",
            "dispatch_outcome=anyarray['accepted','no_send','rejected','uncertain']",
        )
        if normalized not in {expected, array_rendering}:
            raise RuntimeError("Existing notification attempt proof constraint is incompatible")
    else:
        op.create_check_constraint(name, table, proof)


def _valid_schema_three(row) -> bool:
    # Frozen validation: do not import mutable future application validators.
    payload = row["payload"]
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        return False
    if (
        type(payload["schema_version"]) is not int or payload["schema_version"] != 3
        or payload["scope"] != "project_execution+backup_cycles+academy_course_packages"
        or payload["full_host_closure"] is not False
        or type(payload["generation"]) is not int or payload["generation"] < 3
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
        raise RuntimeError("Notification dispatch admission requires PostgreSQL")
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
    # Match runtime admission -> registry lock order before widening the table.
    _expand_registry(bind)
    _expand_attempts(bind)
    if row is None or not _valid_schema_three(row):
        return
    payload = dict(row["payload"])
    payload.update(
        schema_version=4,
        scope="project_execution+backup_cycles+academy_course_packages+notification_delivery_dispatch",
        generation=row["version"] + 1,
    )
    now = bind.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    changed = bind.execute(
        sa.update(records)
        .where(records.c.id == row["id"], records.c.version == row["version"])
        .values(payload=payload, version=payload["generation"], updated_at=now)
        .returning(records.c.id)
    ).scalar_one_or_none()
    if changed != row["id"]:
        raise RuntimeError("Notification coverage migration lost its authority generation")


def downgrade() -> None:
    # Keep schema-4 authority, attempt proofs, and unfinished rows. An older
    # application fails closed on unknown coverage instead of erasing evidence.
    pass
