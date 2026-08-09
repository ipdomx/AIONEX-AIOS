"""Phase 34E 3D resilience, tracing, and idempotency.

Revision ID: 20260809_0014
Revises: 20260809_0013
"""
from alembic import op
import sqlalchemy as sa

revision = "20260809_0014"
down_revision = "20260809_0013"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _unique_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints(table) if item.get("name")}


def upgrade() -> None:
    table = "three_d_generation_jobs"
    cols = _columns(table)
    if "idempotency_key" not in cols:
        op.add_column(table, sa.Column("idempotency_key", sa.String(64), nullable=True))
    if "request_fingerprint" not in cols:
        op.add_column(table, sa.Column("request_fingerprint", sa.String(64), nullable=True))
    if "trace_id" not in cols:
        op.add_column(table, sa.Column("trace_id", sa.String(64), nullable=True))
        op.execute("UPDATE three_d_generation_jobs SET trace_id = id WHERE trace_id IS NULL")
        op.alter_column(table, "trace_id", nullable=False)
    indexes = _indexes(table)
    for name, columns in (
        ("ix_three_d_generation_jobs_request_fingerprint", ["request_fingerprint"]),
        ("ix_three_d_jobs_trace", ["trace_id"]),
    ):
        if name not in indexes:
            op.create_index(name, table, columns)
            indexes.add(name)
    if "uq_three_d_jobs_idempotency_key" not in _unique_names(table):
        op.create_unique_constraint("uq_three_d_jobs_idempotency_key", table, ["idempotency_key"])


def downgrade() -> None:
    table = "three_d_generation_jobs"
    uniques = _unique_names(table)
    if "uq_three_d_jobs_idempotency_key" in uniques:
        op.drop_constraint("uq_three_d_jobs_idempotency_key", table, type_="unique")
    indexes = _indexes(table)
    for name in (
        "ix_three_d_jobs_trace",
        "ix_three_d_generation_jobs_request_fingerprint",
    ):
        if name in indexes:
            op.drop_index(name, table_name=table)
    cols = _columns(table)
    for name in ("trace_id", "request_fingerprint", "idempotency_key"):
        if name in cols:
            op.drop_column(table, name)
