"""Complete identity tenancy, teams, recovery, and MFA persistence.

Revision ID: 20260806_0007
Revises: 20260805_0006
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op

revision = "20260806_0007"
down_revision = "20260805_0006"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_indexes(table) if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    user_columns = _columns(bind, "users")
    if "workspace_id" not in user_columns:
        op.add_column("users", sa.Column("workspace_id", sa.String(36), nullable=True))
        op.create_foreign_key(
            "fk_users_workspace_id_workspaces",
            "users",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "last_active_at" not in user_columns:
        op.add_column("users", sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True))
    indexes = _indexes(bind, "users")
    if "ix_users_workspace_id" not in indexes:
        op.create_index("ix_users_workspace_id", "users", ["workspace_id"], unique=False)
    if "ix_users_last_active_at" not in indexes:
        op.create_index("ix_users_last_active_at", "users", ["last_active_at"], unique=False)

    if "teams" not in tables:
        op.create_table(
            "teams",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("workspace_id", sa.String(36), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("slug", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("organization_id", "slug", name="uq_team_org_slug"),
        )
        op.create_index("ix_teams_organization_id", "teams", ["organization_id"])
        op.create_index("ix_teams_workspace_id", "teams", ["workspace_id"])
        op.create_index("ix_teams_org_status", "teams", ["organization_id", "status"])

    if "team_memberships" not in tables:
        op.create_table(
            "team_memberships",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("team_id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("membership_role", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("team_id", "user_id", name="uq_team_membership"),
        )
        op.create_index("ix_team_memberships_team_id", "team_memberships", ["team_id"])
        op.create_index("ix_team_memberships_user_id", "team_memberships", ["user_id"])
        op.create_index("ix_team_memberships_user_team", "team_memberships", ["user_id", "team_id"])

    if "password_reset_tokens" not in tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("requested_ip", sa.String(64), nullable=True),
            sa.Column("delivery_status", sa.String(32), nullable=False),
            sa.Column("delivery_attempted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
        op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)
        op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"])
        op.create_index("ix_password_reset_user_expiry", "password_reset_tokens", ["user_id", "expires_at"])

    if "user_mfa" not in tables:
        op.create_table(
            "user_mfa",
            sa.Column("user_id", sa.String(36), primary_key=True),
            sa.Column("secret_ciphertext", sa.Text(), nullable=False),
            sa.Column("backup_code_hashes", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_user_mfa_enabled", "user_mfa", ["enabled"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    for table in ("user_mfa", "password_reset_tokens", "team_memberships", "teams"):
        if table in tables:
            op.drop_table(table)
    user_columns = _columns(bind, "users")
    if "last_active_at" in user_columns:
        op.drop_index("ix_users_last_active_at", table_name="users")
        op.drop_column("users", "last_active_at")
    if "workspace_id" in user_columns:
        op.drop_index("ix_users_workspace_id", table_name="users")
        op.drop_constraint("fk_users_workspace_id_workspaces", "users", type_="foreignkey")
        op.drop_column("users", "workspace_id")
