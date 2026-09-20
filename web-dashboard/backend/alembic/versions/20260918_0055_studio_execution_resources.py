"""Permanent Studio ownership and thread evidence, not filesystem settlement.

Revision ID: 20260918_0055
Revises: 20260918_0054

Frozen DDL is compared to existing bootstrap metadata, including exact columns,
constraints and indexes. There is intentionally no business FK which could
cascade-delete evidence. No job adoption, authority change or production action.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260918_0055"
down_revision = "20260918_0054"
branch_labels = None
depends_on = None


def _table(name: str, *, temporary: bool = False) -> sa.Table:
    table = sa.Table(
        name, sa.MetaData(),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False, unique=True),
        sa.Column("worker_incarnation", sa.String(36), nullable=False),
        sa.Column("admitted_generation", sa.Integer(), nullable=False),
        sa.Column("ownership_nonce", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.Column("cleanup_verified", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True)),
        sa.Column("unresolved_reason", sa.String(160)),
        sa.CheckConstraint("admitted_generation >= 7", name="ck_studio_execution_generation"),
        sa.CheckConstraint("state IN ('active', 'unresolved')", name="ck_studio_execution_state"),
        sa.CheckConstraint("phase IN ('claimed', 'executing', 'returned')", name="ck_studio_execution_phase"),
        sa.CheckConstraint("cleanup_verified = false", name="ck_studio_execution_no_settlement"),
        sa.CheckConstraint("updated_at >= started_at", name="ck_studio_execution_clock"),
        sa.CheckConstraint("(phase = 'returned') = (returned_at IS NOT NULL)", name="ck_studio_execution_return"),
        prefixes=["TEMPORARY"] if temporary else [],
    )
    sa.Index("ix_studio_execution_unfinished", table.c.state, table.c.started_at)
    return table


def _signature(bind, name: str, schema: str | None = None) -> dict:
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(name, schema=schema)
    indexes = inspector.get_indexes(name, schema=schema)
    return {
        "columns": sorted((
            item["name"], str(item["type"]), getattr(item["type"], "timezone", None),
            item["nullable"], item.get("default"), item.get("identity"), item.get("computed"),
        ) for item in columns),
        "primary_key": inspector.get_pk_constraint(name, schema=schema)["constrained_columns"],
        "unique": sorted(tuple(item["column_names"]) for item in inspector.get_unique_constraints(name, schema=schema)),
        "checks": sorted((item["name"], item["sqltext"]) for item in inspector.get_check_constraints(name, schema=schema)),
        "indexes": sorted((
            item["name"], tuple(item["column_names"]), item["unique"], item.get("dialect_options", {}),
        ) for item in indexes if not item.get("duplicates_constraint")),
        "foreign_keys": inspector.get_foreign_keys(name, schema=schema),
    }


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Studio execution ownership requires PostgreSQL")
    bind.execute(sa.text("SELECT set_config('lock_timeout', '5s', true)"))
    name = "studio_executions"
    if not sa.inspect(bind).has_table(name):
        _table(name).create(bind)
        return
    # PostgreSQL renders CHECK expressions canonically. Reflect both the existing
    # table and a private, frozen reference to compare the actual definitions,
    # not just names or permissive string matching. Existing rows are untouched.
    reference = _table("_fr06_0055_studio_execution_expected", temporary=True)
    reference.create(bind)
    try:
        temporary_schema = bind.execute(sa.text(
            "SELECT nspname FROM pg_namespace WHERE oid=pg_my_temp_schema()"
        )).scalar_one()
        if _signature(bind, name) != _signature(bind, reference.name, temporary_schema):
            raise RuntimeError("Existing execution ledger does not match the frozen schema")
    finally:
        # Only the temporary reference created above is removed, never evidence.
        reference.drop(bind)


def downgrade() -> None:
    raise RuntimeError("Execution evidence cannot be discarded by downgrade")
