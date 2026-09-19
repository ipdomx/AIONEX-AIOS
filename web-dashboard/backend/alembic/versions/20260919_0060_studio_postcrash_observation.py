"""Retain read-only Studio post-crash observations without authorizing cleanup.

Revision ID: 20260919_0060
Revises: 20260919_0059

No production activation, backfill, filesystem mutation, replay or automatic
reconciliation. Existing metadata is accepted only when it matches frozen DDL.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260919_0060"
down_revision = "20260919_0059"
branch_labels = None
depends_on = None


def _table(name: str, *, temporary: bool = False) -> sa.Table:
    return sa.Table(
        name, sa.MetaData(),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36), nullable=False, unique=True),
        sa.Column("publication_id", sa.String(36), nullable=True, unique=True),
        sa.Column("job_id", sa.String(36), nullable=False, unique=True),
        sa.Column("worker_incarnation", sa.String(36), nullable=False),
        sa.Column("admitted_generation", sa.Integer(), nullable=False),
        sa.Column("proof", sa.JSON(), nullable=False),
        sa.Column("proof_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "admitted_generation >= 7",
            name="ck_studio_crash_observation_generation",
        ),
        prefixes=["TEMPORARY"] if temporary else [],
    )


def _signature(bind, name: str, schema: str | None = None) -> dict:
    inspector = sa.inspect(bind)
    return {
        "columns": sorted((
            item["name"], str(item["type"]),
            getattr(item["type"], "timezone", None),
            item["nullable"], item.get("default"), item.get("identity"),
            item.get("computed"),
        ) for item in inspector.get_columns(name, schema=schema)),
        "primary_key": inspector.get_pk_constraint(
            name, schema=schema
        )["constrained_columns"],
        "unique": sorted(
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(name, schema=schema)
        ),
        "checks": sorted(
            (item["name"], item["sqltext"])
            for item in inspector.get_check_constraints(name, schema=schema)
        ),
        "indexes": sorted((
            item["name"], tuple(item["column_names"]), item["unique"],
            item.get("dialect_options", {}),
        ) for item in inspector.get_indexes(name, schema=schema)
          if not item.get("duplicates_constraint")),
        "foreign_keys": inspector.get_foreign_keys(name, schema=schema),
    }


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Studio post-crash observation requires PostgreSQL")
    bind.execute(sa.text("SELECT set_config('lock_timeout', '5s', true)"))
    name = "studio_crash_observations"
    if not sa.inspect(bind).has_table(name):
        _table(name).create(bind)
        return
    reference = _table("_fr06_0060_studio_crash_observation_expected", temporary=True)
    reference.create(bind)
    try:
        schema = bind.execute(sa.text(
            "SELECT nspname FROM pg_namespace WHERE oid=pg_my_temp_schema()"
        )).scalar_one()
        if _signature(bind, name) != _signature(bind, reference.name, schema):
            raise RuntimeError(
                "Existing Studio crash observation ledger does not match the frozen schema"
            )
    finally:
        reference.drop(bind)


def downgrade() -> None:
    raise RuntimeError(
        "Studio post-crash observation provenance cannot be discarded by downgrade"
    )
