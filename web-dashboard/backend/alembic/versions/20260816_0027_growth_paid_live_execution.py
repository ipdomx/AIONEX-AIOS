"""Add durable GS-12 paid live-execution journal.

Revision ID: 20260816_0027
Revises: 20260815_0026
"""

from alembic import op
import sqlalchemy as sa

revision = "20260816_0027"
down_revision = "20260815_0026"
branch_labels = None
depends_on = None

TABLES = {
    "growth_paid_live_executions",
    "growth_paid_live_execution_steps",
}


def _existing() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing()
    present = TABLES & existing
    if present == TABLES:
        return
    if present:
        raise RuntimeError(f"partial-gs12-live-execution-schema:{sorted(present)}")

    op.create_table(
        "growth_paid_live_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            sa.String(36),
            sa.ForeignKey("growth_paid_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pilot_id",
            sa.String(36),
            sa.ForeignKey("growth_controlled_pilots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False, server_default="meta"),
        sa.Column("scope_ref", sa.String(255), nullable=False),
        sa.Column("creative_identity_ref", sa.String(96), nullable=False),
        sa.Column("plan_version", sa.String(80), nullable=False),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="prepared"),
        sa.Column(
            "authorized_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("authorized_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "manual_review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("provider_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "spend_executed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "automatic_execution_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "campaign_id",
            "plan_digest",
            name="uq_growth_paid_live_execution_campaign_plan",
        ),
    )
    op.create_index(
        "ix_growth_paid_live_executions_org_status_created",
        "growth_paid_live_executions",
        ["organization_id", "status", "created_at"],
    )
    op.create_index(
        "ix_growth_paid_live_executions_pilot_status",
        "growth_paid_live_executions",
        ["pilot_id", "status"],
    )

    op.create_table(
        "growth_paid_live_execution_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(36),
            sa.ForeignKey("growth_paid_live_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_key", sa.String(100), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(36)),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("request_digest", sa.String(64)),
        sa.Column("provider_object_id", sa.String(64)),
        sa.Column("provider_object_ref", sa.String(96)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_call_started_at", sa.DateTime(timezone=True)),
        sa.Column("provider_call_completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(160)),
        sa.Column(
            "manual_review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "execution_id", "step_key", name="uq_growth_paid_live_execution_step_key"
        ),
        sa.UniqueConstraint(
            "execution_id", "step_order", name="uq_growth_paid_live_execution_step_order"
        ),
    )
    op.create_index(
        "ix_growth_paid_live_execution_steps_execution_status_order",
        "growth_paid_live_execution_steps",
        ["execution_id", "status", "step_order"],
    )


def downgrade() -> None:
    existing = _existing()
    if "growth_paid_live_execution_steps" in existing:
        op.drop_table("growth_paid_live_execution_steps")
    if "growth_paid_live_executions" in existing:
        op.drop_table("growth_paid_live_executions")
