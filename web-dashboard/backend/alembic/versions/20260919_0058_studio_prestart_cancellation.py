"""Retain fenced pre-start cancellation; never infer stopped payload work.

Revision ID: 20260919_0058
Revises: 20260919_0057

No production activation, backfill, cleanup, replay or automatic reconciliation.
Bootstrap metadata is accepted only when it exactly matches the frozen DDL.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "20260919_0058"
down_revision = "20260919_0057"
branch_labels = None
depends_on = None


def _table(name: str, *, temporary: bool = False) -> sa.Table:
    return sa.Table(
        name, sa.MetaData(),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36), nullable=False, unique=True),
        sa.Column("job_id", sa.String(36), nullable=False, unique=True),
        sa.Column("worker_incarnation", sa.String(36), nullable=False),
        sa.Column("admitted_generation", sa.Integer(), nullable=False),
        sa.Column("proof", sa.JSON(), nullable=False),
        sa.Column("proof_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("admitted_generation >= 7", name="ck_studio_prestart_generation"),
        prefixes=["TEMPORARY"] if temporary else [],
    )


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
        raise RuntimeError("Studio pre-start cancellation requires PostgreSQL")
    bind.execute(sa.text("SELECT set_config('lock_timeout', '5s', true)"))
    name = "studio_prestart_cancellations"
    if not sa.inspect(bind).has_table(name):
        _table(name).create(bind)
        return
    reference = _table("_fr06_0058_studio_prestart_expected", temporary=True)
    reference.create(bind)
    try:
        temporary_schema = bind.execute(sa.text(
            "SELECT nspname FROM pg_namespace WHERE oid=pg_my_temp_schema()"
        )).scalar_one()
        if _signature(bind, name) != _signature(bind, reference.name, temporary_schema):
            raise RuntimeError("Existing settlement ledger does not match the frozen schema")
    finally:
        reference.drop(bind)


def downgrade() -> None:
    raise RuntimeError("Studio pre-start cancellation provenance cannot be discarded by downgrade")
