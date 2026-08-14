"""Add GS-08 paid campaign simulation persistence.

Revision ID: 20260814_0023
Revises: 20260814_0022
"""

from alembic import op
import sqlalchemy as sa

revision = "20260814_0023"
down_revision = "20260814_0022"
branch_labels = None
depends_on = None

TABLES = {
    "growth_paid_campaigns",
    "growth_paid_ad_sets",
    "growth_paid_creatives",
    "growth_paid_ads",
    "growth_paid_experiments",
    "growth_paid_launch_simulations",
    "growth_paid_decisions",
}


def _existing() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing()
    present = TABLES & existing
    if present == TABLES:
        return
    if present:
        raise RuntimeError(f"partial-gs08-schema:{sorted(present)}")

    op.create_table(
        "growth_paid_campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "brief_id",
            sa.String(36),
            sa.ForeignKey("growth_campaign_briefs.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("objective", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("total_budget_minor", sa.BigInteger(), nullable=False),
        sa.Column("daily_budget_cap_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "simulated_spend_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column(
            "approval_status",
            sa.String(32),
            nullable=False,
            server_default="not_requested",
        ),
        sa.Column(
            "approved_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("stop_loss_policy", sa.JSON(), nullable=False),
        sa.Column("campaign_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "real_spend_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "live_provider_call",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "live_campaign_mutation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "automatic_budget_increase_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_paid_campaigns_org_status_created",
        "growth_paid_campaigns",
        ["organization_id", "status", "created_at"],
    )

    op.create_table(
        "growth_paid_ad_sets",
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
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("placements", sa.JSON(), nullable=False),
        sa.Column(
            "bid_strategy", sa.String(48), nullable=False, server_default="lowest_cost"
        ),
        sa.Column("daily_budget_cap_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "simulated_spend_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_paid_ad_sets_campaign_status",
        "growth_paid_ad_sets",
        ["campaign_id", "status"],
    )
    op.create_table(
        "growth_paid_creatives",
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
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("format", sa.String(40), nullable=False),
        sa.Column("headline", sa.String(300), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_refs", sa.JSON(), nullable=False),
        sa.Column("destination_url", sa.Text()),
        sa.Column("utm", sa.JSON(), nullable=False),
        sa.Column(
            "approval_status",
            sa.String(32),
            nullable=False,
            server_default="not_requested",
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "growth_paid_ads",
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
            "ad_set_id",
            sa.String(36),
            sa.ForeignKey("growth_paid_ad_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "creative_id",
            sa.String(36),
            sa.ForeignKey("growth_paid_creatives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column(
            "simulated_impressions", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "simulated_clicks", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "simulated_conversions", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "simulated_spend_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "simulated_revenue_minor",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "ad_set_id", "creative_id", name="uq_growth_paid_ad_target_creative"
        ),
    )
    op.create_index(
        "ix_growth_paid_ads_campaign_status",
        "growth_paid_ads",
        ["campaign_id", "status"],
    )
    op.create_table(
        "growth_paid_experiments",
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
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("variant_ad_ids", sa.JSON(), nullable=False),
        sa.Column("allocation", sa.JSON(), nullable=False),
        sa.Column(
            "primary_metric",
            sa.String(48),
            nullable=False,
            server_default="conversion_rate",
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_paid_experiments_campaign_status",
        "growth_paid_experiments",
        ["campaign_id", "status"],
    )
    op.create_table(
        "growth_paid_launch_simulations",
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
            "requested_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("seed", sa.String(64), nullable=False),
        sa.Column("simulated_days", sa.Integer(), nullable=False),
        sa.Column(
            "simulated_spend_minor", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column(
            "real_spend_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "live_provider_call",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "live_campaign_mutation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_paid_launch_simulations_campaign_created",
        "growth_paid_launch_simulations",
        ["campaign_id", "created_at"],
    )
    op.create_table(
        "growth_paid_decisions",
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
            "simulation_id",
            sa.String(36),
            sa.ForeignKey("growth_paid_launch_simulations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column(
            "approval_required", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "automatic_execution_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "real_spend_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_paid_decisions_campaign_created",
        "growth_paid_decisions",
        ["campaign_id", "created_at"],
    )


def downgrade() -> None:
    for table in [
        "growth_paid_decisions",
        "growth_paid_launch_simulations",
        "growth_paid_experiments",
        "growth_paid_ads",
        "growth_paid_creatives",
        "growth_paid_ad_sets",
        "growth_paid_campaigns",
    ]:
        op.drop_table(table)
