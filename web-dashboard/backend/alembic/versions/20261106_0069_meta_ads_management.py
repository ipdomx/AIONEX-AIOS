"""Add the P4 Meta Ads schema (ad-account links, insights, campaigns, AI runs).

Revision ID: 20261106_0069
Revises: 20261106_0068 (social inbox)

Creates ``ad_account_links`` (a user's selected Meta ad accounts, per tenant
and user, with incremental-sync and throttle state), ``ad_insights_daily``
(daily Insights per campaign/adset/ad with optional breakdowns, unique on the
natural key so re-ingestion is idempotent), ``ad_insight_sync_runs``
(ingestion audit, including async report runs), ``ad_campaigns`` (campaigns
created from the platform, PAUSED by default, with spend-guard state) and
``ad_recommendation_runs`` (grounded AI recommendations, advisory only). It
adds ``social_oauth_states.purpose`` so the ads permission can be requested
incrementally on the Meta connector. The downgrade drops exactly these
tables and that column.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261106_0069"
down_revision = "20261106_0068"
branch_labels = None
depends_on = None

_TABLES = (
    "ad_account_links",
    "ad_insights_daily",
    "ad_insight_sync_runs",
    "ad_campaigns",
    "ad_recommendation_runs",
)


def _org() -> sa.Column:
    return sa.Column(
        "organization_id",
        sa.String(36),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def _user() -> sa.Column:
    return sa.Column(
        "user_id",
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )


def _link() -> sa.Column:
    return sa.Column(
        "link_id",
        sa.String(36),
        sa.ForeignKey("ad_account_links.id", ondelete="CASCADE"),
        nullable=False,
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _add_purpose_column() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("social_oauth_states")}
    if "purpose" not in columns:
        op.add_column(
            "social_oauth_states",
            sa.Column("purpose", sa.String(16), nullable=False, server_default="social"),
        )


def upgrade() -> None:
    _add_purpose_column()
    inspector = sa.inspect(op.get_bind())
    present = set(inspector.get_table_names()).intersection(_TABLES)
    if present == set(_TABLES):
        return
    if present:
        raise RuntimeError(
            "P4 Meta Ads schema is partially present; manual review is required "
            f"(tables={sorted(present)})"
        )

    op.create_table(
        "ad_account_links",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        _user(),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("social_connections.id", ondelete="SET NULL"),
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("ad_account_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("timezone_name", sa.String(64), nullable=False),
        sa.Column("account_status", sa.Integer(), nullable=False),
        sa.Column("business_name", sa.String(240)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("cpa_target_minor", sa.BigInteger()),
        sa.Column("insights_synced_through", sa.Date()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("next_sync_at", sa.DateTime(timezone=True)),
        sa.Column("throttle_until", sa.DateTime(timezone=True)),
        sa.Column("sync_state", sa.String(24), nullable=False),
        sa.Column("sync_error", sa.String(120)),
        sa.Column("lease_owner", sa.String(80)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "organization_id", "user_id", "ad_account_id", name="uq_ad_account_links_user_account"
        ),
    )
    op.create_index("ix_ad_account_links_organization_id", "ad_account_links", ["organization_id"])
    op.create_index("ix_ad_account_links_user_id", "ad_account_links", ["user_id"])
    op.create_index("ix_ad_account_links_connection_id", "ad_account_links", ["connection_id"])
    op.create_index(
        "ix_ad_account_links_status_next_sync", "ad_account_links", ["status", "next_sync_at"]
    )

    op.create_table(
        "ad_insights_daily",
        sa.Column("id", sa.String(36), primary_key=True),
        _link(),
        _org(),
        _user(),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("object_id", sa.String(32), nullable=False),
        sa.Column("object_name", sa.String(240), nullable=False),
        sa.Column("campaign_id", sa.String(32)),
        sa.Column("adset_id", sa.String(32)),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("breakdown", sa.String(24), nullable=False),
        sa.Column("breakdown_value", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("spend", sa.Float(), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False),
        sa.Column("reach", sa.BigInteger(), nullable=False),
        sa.Column("clicks", sa.BigInteger(), nullable=False),
        sa.Column("link_clicks", sa.BigInteger(), nullable=False),
        sa.Column("conversions", sa.Float(), nullable=False),
        sa.Column("conversion_value", sa.Float(), nullable=False),
        sa.Column("frequency", sa.Float()),
        sa.Column("ctr", sa.Float()),
        sa.Column("cpc", sa.Float()),
        sa.Column("cpm", sa.Float()),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "link_id",
            "level",
            "object_id",
            "day",
            "breakdown",
            "breakdown_value",
            name="uq_ad_insights_daily_natural_key",
        ),
    )
    op.create_index("ix_ad_insights_daily_link_id", "ad_insights_daily", ["link_id"])
    op.create_index(
        "ix_ad_insights_daily_link_level_day",
        "ad_insights_daily",
        ["link_id", "level", "breakdown", "day"],
    )
    op.create_index(
        "ix_ad_insights_daily_org_user_day",
        "ad_insights_daily",
        ["organization_id", "user_id", "day"],
    )

    op.create_table(
        "ad_insight_sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        _link(),
        _org(),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("report_run_ids", sa.JSON(), nullable=False),
        sa.Column("rows_upserted", sa.Integer(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("throttle", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(120)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_ad_insight_sync_runs_link_id", "ad_insight_sync_runs", ["link_id"])
    op.create_index(
        "ix_ad_insight_sync_runs_organization_id", "ad_insight_sync_runs", ["organization_id"]
    )
    op.create_index(
        "ix_ad_insight_sync_runs_link_started", "ad_insight_sync_runs", ["link_id", "started_at"]
    )

    op.create_table(
        "ad_campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        _user(),
        _link(),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("objective", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("daily_budget_minor", sa.BigInteger()),
        sa.Column("lifetime_budget_minor", sa.BigInteger()),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("targeting", sa.JSON(), nullable=False),
        sa.Column("creative", sa.JSON(), nullable=False),
        sa.Column("client_idempotency_key", sa.String(80)),
        sa.Column("meta_campaign_id", sa.String(32)),
        sa.Column("meta_adset_id", sa.String(32)),
        sa.Column("meta_creative_id", sa.String(32)),
        sa.Column("meta_ad_id", sa.String(32)),
        sa.Column("spend_to_date", sa.Float(), nullable=False),
        sa.Column("spend_today", sa.Float(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("paused_at", sa.DateTime(timezone=True)),
        sa.Column("pause_reason", sa.String(64)),
        sa.Column("guard_checked_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(120)),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "user_id", "client_idempotency_key", name="uq_ad_campaigns_user_idempotency"
        ),
    )
    op.create_index("ix_ad_campaigns_organization_id", "ad_campaigns", ["organization_id"])
    op.create_index("ix_ad_campaigns_user_id", "ad_campaigns", ["user_id"])
    op.create_index("ix_ad_campaigns_link_id", "ad_campaigns", ["link_id"])
    op.create_index(
        "ix_ad_campaigns_org_user_status", "ad_campaigns", ["organization_id", "user_id", "status"]
    )

    op.create_table(
        "ad_recommendation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        _org(),
        _user(),
        _link(),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("grounding", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_ad_recommendation_runs_organization_id", "ad_recommendation_runs", ["organization_id"]
    )
    op.create_index("ix_ad_recommendation_runs_user_id", "ad_recommendation_runs", ["user_id"])
    op.create_index("ix_ad_recommendation_runs_link_id", "ad_recommendation_runs", ["link_id"])
    op.create_index(
        "ix_ad_recommendation_runs_org_user_created",
        "ad_recommendation_runs",
        ["organization_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
    columns = {item["name"] for item in sa.inspect(bind).get_columns("social_oauth_states")}
    if "purpose" in columns:
        op.drop_column("social_oauth_states", "purpose")
