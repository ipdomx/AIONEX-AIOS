"""Add GS-12 controlled live-pilot safety gate.

Revision ID: 20260815_0025
Revises: 20260815_0024
"""

from alembic import op
import sqlalchemy as sa

revision = "20260815_0025"
down_revision = "20260815_0024"
branch_labels = None
depends_on = None

TABLE = "growth_controlled_pilots"


def _existing() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if TABLE in _existing():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_scope", sa.String(80), nullable=False),
        sa.Column("scope_ref", sa.String(255)),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column(
            "owner_approved_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("owner_approved_at", sa.DateTime(timezone=True)),
        sa.Column("owner_approval_reference", sa.String(240)),
        sa.Column(
            "legal_policy_acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("legal_policy_reference", sa.String(500)),
        sa.Column(
            "legal_acknowledged_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("legal_acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("currency", sa.String(3)),
        sa.Column("max_total_budget_minor", sa.BigInteger()),
        sa.Column("max_daily_budget_minor", sa.BigInteger()),
        sa.Column("max_cpa_minor", sa.BigInteger()),
        sa.Column("min_roas", sa.Float()),
        sa.Column(
            "launch_authorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "launch_authorized_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("launch_authorized_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("armed_at", sa.DateTime(timezone=True)),
        sa.Column("disarmed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "live_provider_mutation_allowed",
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
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("blocked_reasons", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_controlled_pilots_org_provider_status",
        TABLE,
        ["organization_id", "provider", "status"],
    )
    op.create_index("ix_growth_controlled_pilots_expires_at", TABLE, ["expires_at"])
    op.create_index(
        "ix_growth_controlled_pilots_organization_id", TABLE, ["organization_id"]
    )
    op.create_index(
        "ix_growth_controlled_pilots_created_by_id", TABLE, ["created_by_id"]
    )
    op.create_index("ix_growth_controlled_pilots_provider", TABLE, ["provider"])
    op.create_index("ix_growth_controlled_pilots_mode", TABLE, ["mode"])
    op.create_index("ix_growth_controlled_pilots_status", TABLE, ["status"])
    op.create_index(
        "ix_growth_controlled_pilots_owner_approved_by_id",
        TABLE,
        ["owner_approved_by_id"],
    )
    op.create_index(
        "ix_growth_controlled_pilots_legal_acknowledged_by_id",
        TABLE,
        ["legal_acknowledged_by_id"],
    )
    op.create_index(
        "ix_growth_controlled_pilots_launch_authorized_by_id",
        TABLE,
        ["launch_authorized_by_id"],
    )


def downgrade() -> None:
    if TABLE in _existing():
        op.drop_table(TABLE)
