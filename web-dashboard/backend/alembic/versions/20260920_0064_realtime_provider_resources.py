"""Add permanent Realtime provider-resource ownership evidence.

Revision ID: 20260920_0064
Revises: 20260920_0063

This is source infrastructure only. It does not adopt existing rooms, issue
provider calls, migrate business rows, widen admission, or prove host drain.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260920_0064"
down_revision = "20260920_0063"
branch_labels = None
depends_on = None


def _table(name: str, *, temporary: bool = False) -> sa.Table:
    table = sa.Table(
        name, sa.MetaData(),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("local_resource_id", sa.String(36), nullable=False),
        sa.Column("owner_incarnation", sa.String(36), nullable=False),
        sa.Column("admitted_generation", sa.Integer(), nullable=False),
        sa.Column("admitted_operation_id", sa.String(36), nullable=False),
        sa.Column("ownership_nonce", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("provider_ref_sha256", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("provider_started_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("unresolved_reason", sa.String(160)),
        sa.CheckConstraint(
            "resource_kind IN ('room', 'participant_session', 'egress', 'recording_file')",
            name="ck_realtime_provider_resource_kind",
        ),
        sa.CheckConstraint(
            "state IN ('reserved', 'submitted', 'active', 'unresolved', 'settled')",
            name="ck_realtime_provider_resource_state",
        ),
        sa.CheckConstraint(
            "admitted_generation > 0", name="ck_realtime_provider_resource_generation"
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at >= started_at",
            name="ck_realtime_provider_resource_expiry",
        ),
        sa.CheckConstraint(
            "(state = 'unresolved' AND unresolved_reason IS NOT NULL) OR "
            "(state != 'unresolved' AND unresolved_reason IS NULL)",
            name="ck_realtime_provider_resource_unresolved",
        ),
        sa.CheckConstraint(
            "(state = 'settled' AND settled_at IS NOT NULL) OR "
            "(state != 'settled' AND settled_at IS NULL)",
            name="ck_realtime_provider_resource_settlement",
        ),
        prefixes=["TEMPORARY"] if temporary else [],
    )
    sa.Index(
        "uq_realtime_provider_resource_unfinished_local",
        table.c.organization_id, table.c.resource_kind, table.c.local_resource_id,
        unique=True, postgresql_where=sa.text("state != 'settled'"),
    )
    sa.Index("ix_realtime_provider_resource_unfinished", table.c.state, table.c.expires_at)
    sa.Index(
        "ix_realtime_provider_resource_org_kind_state",
        table.c.organization_id, table.c.resource_kind, table.c.state,
    )
    return table


def _signature(bind, name: str, schema: str | None = None) -> dict:
    inspector = sa.inspect(bind)
    return {
        "columns": sorted((
            item["name"], str(item["type"]), getattr(item["type"], "timezone", None),
            item["nullable"], item.get("default"), item.get("identity"), item.get("computed"),
        ) for item in inspector.get_columns(name, schema=schema)),
        "primary_key": inspector.get_pk_constraint(name, schema=schema)["constrained_columns"],
        "unique": sorted(tuple(item["column_names"]) for item in inspector.get_unique_constraints(name, schema=schema)),
        "checks": sorted((item["name"], item["sqltext"]) for item in inspector.get_check_constraints(name, schema=schema)),
        "indexes": sorted((
            item["name"], tuple(item["column_names"]), item["unique"], item.get("dialect_options", {}),
        ) for item in inspector.get_indexes(name, schema=schema) if not item.get("duplicates_constraint")),
        "foreign_keys": inspector.get_foreign_keys(name, schema=schema),
    }


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Realtime provider ownership requires PostgreSQL")
    bind.execute(sa.text("SELECT set_config('lock_timeout', '5s', true)"))
    name = "realtime_provider_resources"
    if not sa.inspect(bind).has_table(name):
        _table(name).create(bind)
        return
    reference = _table("_fr06_0064_realtime_provider_expected", temporary=True)
    reference.create(bind)
    try:
        temporary_schema = bind.execute(sa.text(
            "SELECT nspname FROM pg_namespace WHERE oid=pg_my_temp_schema()"
        )).scalar_one()
        if _signature(bind, name) != _signature(bind, reference.name, temporary_schema):
            raise RuntimeError("Existing Realtime provider registry does not match frozen schema")
    finally:
        reference.drop(bind)


def downgrade() -> None:
    raise RuntimeError("Realtime provider ownership evidence cannot be discarded by downgrade")
