"""Permanent Security Lab execution/resource evidence.

Revision ID: 20260918_0053
Revises: 20260917_0052

This adds storage only. It does not start workers, touch jobs, widen the existing
partial authority, or claim deployment/host closure. Evidence has no cascading
business foreign key and survives a downgrade for forward reconciliation.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260918_0053"
down_revision = "20260917_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Scan execution ownership requires PostgreSQL")
    op.execute("SELECT set_config('lock_timeout', '5s', true)")
    op.create_table(
        "security_scan_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_id", sa.String(36), nullable=False, unique=True),
        sa.Column("worker_incarnation", sa.String(36), nullable=False),
        sa.Column("admitted_generation", sa.Integer(), nullable=False),
        sa.Column("ownership_nonce", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.Column("zap_owner_key", sa.String(64), unique=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("operation_stopped_at", sa.DateTime(timezone=True)),
        sa.Column("supervisor_stopped_at", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(32)),
        sa.Column("unresolved_reason", sa.String(160)),
        sa.CheckConstraint("admitted_generation > 0", name="ck_scan_execution_generation"),
        sa.CheckConstraint("state IN ('active', 'unresolved', 'settled')", name="ck_scan_execution_state"),
        sa.CheckConstraint("phase IN ('claimed', 'executing', 'returned')", name="ck_scan_execution_phase"),
        sa.CheckConstraint("lease_expires_at >= heartbeat_at", name="ck_scan_execution_deadline"),
        sa.CheckConstraint(
            "state != 'settled' OR (phase = 'returned' AND operation_stopped_at IS NOT NULL "
            "AND supervisor_stopped_at IS NOT NULL AND settled_at IS NOT NULL AND zap_owner_key IS NULL)",
            name="ck_scan_execution_settlement",
        ),
    )
    op.create_index("ix_scan_execution_unfinished", "security_scan_executions", ["state", "lease_expires_at"])


def downgrade() -> None:
    # Removing this ledger would destroy unresolved resource and engine owners.
    # Downgrade is explicitly refused; old binaries must not run uninstrumented.
    raise RuntimeError("Execution evidence cannot be discarded by downgrade")
