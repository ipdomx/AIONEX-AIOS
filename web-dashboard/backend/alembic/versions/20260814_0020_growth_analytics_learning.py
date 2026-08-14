"""Add GS-05 analytics and learning ledger persistence.

Revision ID: 20260814_0020
Revises: 20260814_0019
"""

from alembic import op
import sqlalchemy as sa

revision = "20260814_0020"
down_revision = "20260814_0019"
branch_labels = None
depends_on = None

_TABLES = (
    "growth_performance_observations",
    "growth_learning_entries",
    "growth_optimization_recommendations",
)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing.intersection(_TABLES)
    if present == set(_TABLES):
        return
    if present:
        raise RuntimeError(
            "GS-05 analytics schema is partially present; manual review is required "
            f"before migration (present={sorted(present)})"
        )

    op.create_table(
        "growth_performance_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recorded_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.String(48), nullable=False),
        sa.Column("subject_id", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(40)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False),
        sa.Column("reach", sa.BigInteger(), nullable=False),
        sa.Column("engagements", sa.BigInteger(), nullable=False),
        sa.Column("clicks", sa.BigInteger(), nullable=False),
        sa.Column("conversions", sa.BigInteger(), nullable=False),
        sa.Column("spend_minor", sa.BigInteger(), nullable=False),
        sa.Column("revenue_minor", sa.BigInteger(), nullable=False),
        sa.Column("followers_delta", sa.BigInteger(), nullable=False),
        sa.Column("extra_metrics", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("sample_quality", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_observations_organization_id",
        "growth_performance_observations",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_observations_recorded_by_id",
        "growth_performance_observations",
        ["recorded_by_id"],
    )
    op.create_index(
        "ix_growth_observations_provider",
        "growth_performance_observations",
        ["provider"],
    )
    op.create_index(
        "ix_growth_observations_period_end",
        "growth_performance_observations",
        ["period_end"],
    )
    op.create_index(
        "ix_growth_observations_org_subject_period",
        "growth_performance_observations",
        ["organization_id", "subject_type", "subject_id", "period_end"],
    )
    op.create_index(
        "ix_growth_observations_org_source_created",
        "growth_performance_observations",
        ["organization_id", "source", "created_at"],
    )

    op.create_table(
        "growth_learning_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            sa.String(36),
            sa.ForeignKey("growth_performance_observations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.String(48), nullable=False),
        sa.Column("subject_id", sa.String(160), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("normalized_metrics", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("occurrence_index", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("observation_id", name="uq_growth_learning_observation"),
    )
    op.create_index(
        "ix_growth_learning_organization_id",
        "growth_learning_entries",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_learning_observation_id",
        "growth_learning_entries",
        ["observation_id"],
    )
    op.create_index(
        "ix_growth_learning_outcome",
        "growth_learning_entries",
        ["outcome"],
    )
    op.create_index(
        "ix_growth_learning_fingerprint",
        "growth_learning_entries",
        ["fingerprint"],
    )
    op.create_index(
        "ix_growth_learning_org_fingerprint_created",
        "growth_learning_entries",
        ["organization_id", "fingerprint", "created_at"],
    )
    op.create_index(
        "ix_growth_learning_org_outcome_created",
        "growth_learning_entries",
        ["organization_id", "outcome", "created_at"],
    )

    op.create_table(
        "growth_optimization_recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "learning_entry_id",
            sa.String(36),
            sa.ForeignKey("growth_learning_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.String(48), nullable=False),
        sa.Column("subject_id", sa.String(160), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("replay_eligible", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("auto_optimization_allowed", sa.Boolean(), nullable=False),
        sa.Column("auto_replay_allowed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "learning_entry_id", name="uq_growth_recommendation_learning"
        ),
    )
    op.create_index(
        "ix_growth_recommendations_organization_id",
        "growth_optimization_recommendations",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_recommendations_learning_entry_id",
        "growth_optimization_recommendations",
        ["learning_entry_id"],
    )
    op.create_index(
        "ix_growth_recommendations_fingerprint",
        "growth_optimization_recommendations",
        ["fingerprint"],
    )
    op.create_index(
        "ix_growth_recommendations_replay_eligible",
        "growth_optimization_recommendations",
        ["replay_eligible"],
    )
    op.create_index(
        "ix_growth_recommendations_org_action_created",
        "growth_optimization_recommendations",
        ["organization_id", "action", "created_at"],
    )
    op.create_index(
        "ix_growth_recommendations_org_eligible_created",
        "growth_optimization_recommendations",
        ["organization_id", "replay_eligible", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("growth_optimization_recommendations")
    op.drop_table("growth_learning_entries")
    op.drop_table("growth_performance_observations")
