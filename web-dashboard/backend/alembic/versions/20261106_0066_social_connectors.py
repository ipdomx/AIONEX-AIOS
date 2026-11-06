"""Add the P3 social connector framework schema (OAuth grants and state).

Revision ID: 20261106_0066
Revises: 20261025_0065

Creates ``social_connections`` (one user's encrypted OAuth grant per provider
account) and ``social_oauth_states`` (single-use, browser-bound OAuth state with
an encrypted PKCE verifier), and extends the GS-03 ``growth_social_accounts``
registry with nullable columns for OAuth-connected assets (connection link,
avatar, scopes and the encrypted asset token). Existing GS-03 rows keep NULL in
every new column. The downgrade removes exactly what the upgrade adds.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261106_0066"
down_revision = "20261025_0065"
branch_labels = None
depends_on = None

_TABLES = ("social_connections", "social_oauth_states")
_ACCOUNT_COLUMNS = (
    "connection_id",
    "connected_via",
    "avatar_url",
    "scopes",
    "token_ciphertext",
)
_ACCOUNT_FK = "fk_growth_social_accounts_connection_id"
_ACCOUNT_INDEX = "ix_growth_social_accounts_connection_id"


def _account_columns(inspector: sa.Inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns("growth_social_accounts")}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    present_tables = existing_tables.intersection(_TABLES)
    present_columns = _account_columns(inspector).intersection(_ACCOUNT_COLUMNS)
    if present_tables == set(_TABLES) and present_columns == set(_ACCOUNT_COLUMNS):
        return
    if present_tables or present_columns:
        raise RuntimeError(
            "P3 social connector schema is partially present; manual review is "
            f"required (tables={sorted(present_tables)}, columns={sorted(present_columns)})"
        )

    op.create_table(
        "social_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("avatar_url", sa.String(1024)),
        sa.Column("requested_scopes", sa.JSON(), nullable=False),
        sa.Column("granted_scopes", sa.JSON(), nullable=False),
        sa.Column("token_ciphertext", sa.Text()),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("health_state", sa.String(32), nullable=False),
        sa.Column("health_reasons", sa.JSON(), nullable=False),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "provider",
            "external_user_id",
            name="uq_social_connection_user_provider_external",
        ),
    )
    op.create_index(
        "ix_social_connections_organization_id",
        "social_connections",
        ["organization_id"],
    )
    op.create_index("ix_social_connections_user_id", "social_connections", ["user_id"])
    op.create_index(
        "ix_social_connections_org_user_provider",
        "social_connections",
        ["organization_id", "user_id", "provider"],
    )

    op.create_table(
        "social_oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("browser_binding_hash", sa.String(64), nullable=False),
        sa.Column("code_verifier_ciphertext", sa.Text()),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("state_hash", name="uq_social_oauth_states_state_hash"),
    )
    op.create_index(
        "ix_social_oauth_states_organization_id",
        "social_oauth_states",
        ["organization_id"],
    )
    op.create_index("ix_social_oauth_states_user_id", "social_oauth_states", ["user_id"])
    op.create_index(
        "ix_social_oauth_states_user_expiry",
        "social_oauth_states",
        ["user_id", "expires_at"],
    )

    op.add_column(
        "growth_social_accounts", sa.Column("connection_id", sa.String(36))
    )
    op.add_column(
        "growth_social_accounts", sa.Column("connected_via", sa.String(24))
    )
    op.add_column("growth_social_accounts", sa.Column("avatar_url", sa.String(1024)))
    op.add_column("growth_social_accounts", sa.Column("scopes", sa.JSON()))
    op.add_column("growth_social_accounts", sa.Column("token_ciphertext", sa.Text()))
    op.create_foreign_key(
        _ACCOUNT_FK,
        "growth_social_accounts",
        "social_connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(_ACCOUNT_INDEX, "growth_social_accounts", ["connection_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = _account_columns(inspector)
    if "connection_id" in columns:
        if _ACCOUNT_INDEX in {
            index["name"] for index in inspector.get_indexes("growth_social_accounts")
        }:
            op.drop_index(_ACCOUNT_INDEX, table_name="growth_social_accounts")
        if _ACCOUNT_FK in {
            key["name"] for key in inspector.get_foreign_keys("growth_social_accounts")
        }:
            op.drop_constraint(_ACCOUNT_FK, "growth_social_accounts", type_="foreignkey")
    for column in reversed(_ACCOUNT_COLUMNS):
        if column in columns:
            op.drop_column("growth_social_accounts", column)
    existing_tables = set(inspector.get_table_names())
    for table in ("social_oauth_states", "social_connections"):
        if table in existing_tables:
            op.drop_table(table)
