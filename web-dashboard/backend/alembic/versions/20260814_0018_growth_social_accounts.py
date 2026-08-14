"""Add GS-03 managed social account registry and provider capability matrix.

Revision ID: 20260814_0018
Revises: 20260814_0017
"""

from alembic import op
import sqlalchemy as sa

revision = "20260814_0018"
down_revision = "20260814_0017"
branch_labels = None
depends_on = None

_TABLES = (
    "growth_social_accounts",
    "growth_social_provider_capabilities",
)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing.intersection(_TABLES)
    if present == set(_TABLES):
        return
    if present:
        raise RuntimeError(
            "GS-03 social schema is partially present; manual review is required "
            f"before migration (present={sorted(present)})"
        )

    op.create_table(
        "growth_social_accounts",
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
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "team_id",
            sa.String(36),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("account_kind", sa.String(48), nullable=False),
        sa.Column("external_account_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("public_handle", sa.String(255)),
        sa.Column("credential_ref", sa.String(320)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("health_state", sa.String(32), nullable=False),
        sa.Column("health_reasons", sa.JSON(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column("paused_at", sa.DateTime(timezone=True)),
        sa.Column("provider_metadata", sa.JSON(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "external_account_id",
            name="uq_growth_social_account_provider_external",
        ),
    )
    op.create_index(
        "ix_growth_social_accounts_organization_id",
        "growth_social_accounts",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_social_accounts_created_by_id",
        "growth_social_accounts",
        ["created_by_id"],
    )
    op.create_index(
        "ix_growth_social_accounts_workspace_id",
        "growth_social_accounts",
        ["workspace_id"],
    )
    op.create_index(
        "ix_growth_social_accounts_team_id",
        "growth_social_accounts",
        ["team_id"],
    )
    op.create_index(
        "ix_growth_social_accounts_provider",
        "growth_social_accounts",
        ["provider"],
    )
    op.create_index(
        "ix_growth_social_accounts_org_provider_status",
        "growth_social_accounts",
        ["organization_id", "provider", "status"],
    )
    op.create_index(
        "ix_growth_social_accounts_token_expiry",
        "growth_social_accounts",
        ["token_expires_at"],
    )

    op.create_table(
        "growth_social_provider_capabilities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("verification_state", sa.String(32), nullable=False),
        sa.Column("mutation_class", sa.String(24), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("simulated_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "capability",
            name="uq_growth_social_provider_capability",
        ),
    )
    op.create_index(
        "ix_growth_social_provider_capabilities_provider",
        "growth_social_provider_capabilities",
        ["provider"],
    )
    op.create_index(
        "ix_growth_social_provider_capability_state",
        "growth_social_provider_capabilities",
        ["provider", "verification_state"],
    )


def downgrade() -> None:
    op.drop_table("growth_social_provider_capabilities")
    op.drop_table("growth_social_accounts")
