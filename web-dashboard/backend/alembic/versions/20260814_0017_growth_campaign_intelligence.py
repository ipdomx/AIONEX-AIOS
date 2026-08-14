"""Add GS-02 growth campaign intelligence persistence.

Revision ID: 20260814_0017
Revises: 20260810_0016
"""
from alembic import op
import sqlalchemy as sa

revision = "20260814_0017"
down_revision = "20260810_0016"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind=op.get_bind(); existing=set(sa.inspect(bind).get_table_names())
    if "growth_campaign_briefs" not in existing:
        op.create_table("growth_campaign_briefs",
            sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
            sa.Column("name", sa.String(240), nullable=False), sa.Column("objective", sa.String(80), nullable=False), sa.Column("product_summary", sa.Text(), nullable=False),
            sa.Column("target_markets", sa.JSON(), nullable=False), sa.Column("audience_hypotheses", sa.JSON(), nullable=False), sa.Column("competitor_hypotheses", sa.JSON(), nullable=False),
            sa.Column("offer_hypotheses", sa.JSON(), nullable=False), sa.Column("channel_hypotheses", sa.JSON(), nullable=False), sa.Column("budget_minor", sa.BigInteger(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False), sa.Column("evidence", sa.JSON(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_growth_campaign_briefs_org_status_created", "growth_campaign_briefs", ["organization_id","status","created_at"])
        op.create_index("ix_growth_campaign_briefs_organization_id", "growth_campaign_briefs", ["organization_id"])
        op.create_index("ix_growth_campaign_briefs_created_by_id", "growth_campaign_briefs", ["created_by_id"])
        op.create_index("ix_growth_campaign_briefs_project_id", "growth_campaign_briefs", ["project_id"])
    existing=set(sa.inspect(bind).get_table_names())
    if "growth_campaign_simulations" not in existing:
        op.create_table("growth_campaign_simulations",
            sa.Column("id", sa.String(36), primary_key=True), sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("brief_id", sa.String(36), sa.ForeignKey("growth_campaign_briefs.id", ondelete="CASCADE"), nullable=False), sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("scenario", sa.String(32), nullable=False), sa.Column("confidence", sa.Float(), nullable=False), sa.Column("estimated_reach_min", sa.BigInteger(), nullable=False), sa.Column("estimated_reach_max", sa.BigInteger(), nullable=False),
            sa.Column("estimated_clicks_min", sa.BigInteger(), nullable=False), sa.Column("estimated_clicks_max", sa.BigInteger(), nullable=False), sa.Column("estimated_conversions_min", sa.BigInteger(), nullable=False), sa.Column("estimated_conversions_max", sa.BigInteger(), nullable=False),
            sa.Column("estimated_cpa_minor", sa.BigInteger()), sa.Column("reason_codes", sa.JSON(), nullable=False), sa.Column("assumptions", sa.JSON(), nullable=False), sa.Column("result", sa.JSON(), nullable=False), sa.Column("real_spend_allowed", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_growth_campaign_simulations_brief_created", "growth_campaign_simulations", ["brief_id","created_at"])
        op.create_index("ix_growth_campaign_simulations_organization_id", "growth_campaign_simulations", ["organization_id"])
        op.create_index("ix_growth_campaign_simulations_brief_id", "growth_campaign_simulations", ["brief_id"])
        op.create_index("ix_growth_campaign_simulations_requested_by_id", "growth_campaign_simulations", ["requested_by_id"])

def downgrade() -> None:
    op.drop_table("growth_campaign_simulations")
    op.drop_table("growth_campaign_briefs")
