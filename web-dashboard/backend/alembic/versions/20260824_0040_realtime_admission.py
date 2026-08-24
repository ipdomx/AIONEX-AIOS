"""Add durable tenant-scoped realtime admission authority.

Revision ID: 20260824_0040
Revises: 20260823_0039
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0040"
down_revision: str | None = "20260823_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_columns(
    inspector: sa.Inspector, table_name: str, required: set[str]
) -> None:
    actual = {column["name"] for column in inspector.get_columns(table_name)}
    missing = sorted(required - actual)
    if missing:
        raise RuntimeError(
            f"Realtime admission table {table_name} is missing columns: "
            + ", ".join(missing)
        )


def _ensure_unique_constraint(
    bind: sa.Connection,
    table_name: str,
    constraint_name: str,
    columns: list[str],
) -> None:
    inspector = sa.inspect(bind)
    names = {
        item.get("name")
        for item in inspector.get_unique_constraints(table_name)
        if item.get("name")
    }
    if constraint_name not in names:
        op.create_unique_constraint(constraint_name, table_name, columns)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required_dependencies = {"organizations", "users", "workspaces", "projects"}
    missing_dependencies = sorted(required_dependencies - tables)
    if missing_dependencies:
        raise RuntimeError(
            "Realtime admission migration requires tables: "
            + ", ".join(missing_dependencies)
        )

    for table_name, constraint_name, columns in (
        ("users", "uq_users_id_org", ["id", "organization_id"]),
        ("workspaces", "uq_workspace_id_org", ["id", "organization_id"]),
        ("projects", "uq_project_id_org", ["id", "organization_id"]),
    ):
        _ensure_unique_constraint(bind, table_name, constraint_name, columns)

    if "realtime_tenant_quotas" not in tables:
        op.create_table(
            "realtime_tenant_quotas",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "max_concurrent_rooms",
                sa.Integer(),
                nullable=False,
                server_default="25",
            ),
            sa.Column(
                "max_participants_per_room",
                sa.Integer(),
                nullable=False,
                server_default="100",
            ),
            sa.Column(
                "max_concurrent_participants",
                sa.Integer(),
                nullable=False,
                server_default="250",
            ),
            sa.Column(
                "max_publishers_per_room",
                sa.Integer(),
                nullable=False,
                server_default="25",
            ),
            sa.Column(
                "max_screen_shares_per_room",
                sa.Integer(),
                nullable=False,
                server_default="4",
            ),
            sa.Column(
                "max_concurrent_recordings",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "admission_window_seconds",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "max_admissions_per_window",
                sa.Integer(),
                nullable=False,
                server_default="300",
            ),
            sa.Column(
                "grant_ttl_seconds",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            ),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "max_concurrent_rooms BETWEEN 1 AND 10000",
                name="ck_realtime_quota_room_limit",
            ),
            sa.CheckConstraint(
                "max_participants_per_room BETWEEN 1 AND 10000",
                name="ck_realtime_quota_room_participant_limit",
            ),
            sa.CheckConstraint(
                "max_concurrent_participants BETWEEN 1 AND 100000",
                name="ck_realtime_quota_tenant_participant_limit",
            ),
            sa.CheckConstraint(
                "max_publishers_per_room BETWEEN 0 AND 10000",
                name="ck_realtime_quota_publisher_limit",
            ),
            sa.CheckConstraint(
                "max_screen_shares_per_room BETWEEN 0 AND 1000",
                name="ck_realtime_quota_screen_share_limit",
            ),
            sa.CheckConstraint(
                "max_concurrent_recordings BETWEEN 0 AND 1000",
                name="ck_realtime_quota_recording_limit",
            ),
            sa.CheckConstraint(
                "admission_window_seconds BETWEEN 1 AND 3600",
                name="ck_realtime_quota_admission_window",
            ),
            sa.CheckConstraint(
                "max_admissions_per_window BETWEEN 1 AND 100000",
                name="ck_realtime_quota_admission_rate",
            ),
            sa.CheckConstraint(
                "grant_ttl_seconds BETWEEN 5 AND 300",
                name="ck_realtime_quota_grant_ttl",
            ),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id", name="uq_realtime_tenant_quota_organization"
            ),
        )
        op.create_index(
            "ix_realtime_tenant_quotas_organization_id",
            "realtime_tenant_quotas",
            ["organization_id"],
        )
        op.create_index(
            "ix_realtime_tenant_quotas_enabled",
            "realtime_tenant_quotas",
            ["organization_id", "enabled"],
        )
    else:
        _assert_columns(
            inspector,
            "realtime_tenant_quotas",
            {
                "id",
                "organization_id",
                "enabled",
                "max_concurrent_rooms",
                "max_participants_per_room",
                "max_concurrent_participants",
                "max_publishers_per_room",
                "max_screen_shares_per_room",
                "max_concurrent_recordings",
                "admission_window_seconds",
                "max_admissions_per_window",
                "grant_ttl_seconds",
                "policy",
                "version",
                "created_at",
                "updated_at",
            },
        )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "realtime_rooms" not in tables:
        op.create_table(
            "realtime_rooms",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=True),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("created_by_id", sa.String(length=36), nullable=False),
            sa.Column("room_key", sa.String(length=160), nullable=False),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column(
                "room_type",
                sa.String(length=32),
                nullable=False,
                server_default="meeting",
            ),
            sa.Column(
                "media_mode",
                sa.String(length=32),
                nullable=False,
                server_default="audio_video",
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="planned",
            ),
            sa.Column(
                "provider_adapter",
                sa.String(length=40),
                nullable=False,
                server_default="unassigned",
            ),
            sa.Column("provider_room_id_sha256", sa.String(length=64), nullable=True),
            sa.Column(
                "max_participants",
                sa.Integer(),
                nullable=False,
                server_default="50",
            ),
            sa.Column(
                "allow_screen_share",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "recording_policy",
                sa.String(length=32),
                nullable=False,
                server_default="disabled",
            ),
            sa.Column(
                "encryption_policy",
                sa.String(length=40),
                nullable=False,
                server_default="transport_required",
            ),
            sa.Column(
                "admission_policy",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column(
                "fencing_token", sa.BigInteger(), nullable=False, server_default="0"
            ),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "max_participants BETWEEN 1 AND 10000",
                name="ck_realtime_room_participant_limit",
            ),
            sa.CheckConstraint(
                "fencing_token >= 0", name="ck_realtime_room_fencing_token"
            ),
            sa.ForeignKeyConstraint(
                ["created_by_id", "organization_id"],
                ["users.id", "users.organization_id"],
                name="fk_realtime_room_creator_tenant",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["project_id", "organization_id"],
                ["projects.id", "projects.organization_id"],
                name="fk_realtime_room_project_tenant",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id", "organization_id"],
                ["workspaces.id", "workspaces.organization_id"],
                name="fk_realtime_room_workspace_tenant",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "id", "organization_id", name="uq_realtime_room_id_org"
            ),
            sa.UniqueConstraint(
                "organization_id", "room_key", name="uq_realtime_room_org_key"
            ),
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_realtime_room_org_idempotency",
            ),
        )
        for name, columns in (
            ("ix_realtime_rooms_organization_id", ["organization_id"]),
            ("ix_realtime_rooms_workspace_id", ["workspace_id"]),
            ("ix_realtime_rooms_project_id", ["project_id"]),
            ("ix_realtime_rooms_created_by_id", ["created_by_id"]),
            ("ix_realtime_rooms_status", ["status"]),
            ("ix_realtime_rooms_expires_at", ["expires_at"]),
            (
                "ix_realtime_rooms_org_status_updated",
                ["organization_id", "status", "updated_at"],
            ),
            (
                "ix_realtime_rooms_org_workspace",
                ["organization_id", "workspace_id"],
            ),
        ):
            op.create_index(name, "realtime_rooms", columns)
    else:
        _assert_columns(
            inspector,
            "realtime_rooms",
            {
                "id",
                "organization_id",
                "workspace_id",
                "project_id",
                "created_by_id",
                "room_key",
                "idempotency_key",
                "room_type",
                "media_mode",
                "status",
                "provider_adapter",
                "provider_room_id_sha256",
                "max_participants",
                "allow_screen_share",
                "recording_policy",
                "encryption_policy",
                "admission_policy",
                "fencing_token",
                "opened_at",
                "closed_at",
                "expires_at",
                "version",
                "created_at",
                "updated_at",
            },
        )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "realtime_participants" not in tables:
        op.create_table(
            "realtime_participants",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("room_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("participant_key", sa.String(length=160), nullable=False),
            sa.Column(
                "role",
                sa.String(length=32),
                nullable=False,
                server_default="attendee",
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="admitted",
            ),
            sa.Column(
                "can_publish", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "can_subscribe", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "can_screen_share",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "hidden", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("node_id", sa.String(length=160), nullable=True),
            sa.Column(
                "connection_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "capabilities",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "connection_count >= 0",
                name="ck_realtime_participant_connection_count",
            ),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["room_id", "organization_id"],
                ["realtime_rooms.id", "realtime_rooms.organization_id"],
                name="fk_realtime_participant_room_tenant",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id", "organization_id"],
                ["users.id", "users.organization_id"],
                name="fk_realtime_participant_user_tenant",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "id", "organization_id", name="uq_realtime_participant_id_org"
            ),
            sa.UniqueConstraint(
                "organization_id",
                "room_id",
                "participant_key",
                name="uq_realtime_participant_org_room_key",
            ),
        )
        for name, columns in (
            ("ix_realtime_participants_organization_id", ["organization_id"]),
            ("ix_realtime_participants_room_id", ["room_id"]),
            ("ix_realtime_participants_user_id", ["user_id"]),
            ("ix_realtime_participants_status", ["status"]),
            ("ix_realtime_participants_node_id", ["node_id"]),
            ("ix_realtime_participants_last_seen_at", ["last_seen_at"]),
            (
                "ix_realtime_participants_org_room_status",
                ["organization_id", "room_id", "status"],
            ),
            (
                "ix_realtime_participants_org_user_status",
                ["organization_id", "user_id", "status"],
            ),
        ):
            op.create_index(name, "realtime_participants", columns)
    else:
        _assert_columns(
            inspector,
            "realtime_participants",
            {
                "id",
                "organization_id",
                "room_id",
                "user_id",
                "participant_key",
                "role",
                "status",
                "can_publish",
                "can_subscribe",
                "can_screen_share",
                "hidden",
                "node_id",
                "connection_count",
                "capabilities",
                "joined_at",
                "last_seen_at",
                "left_at",
                "revoked_at",
                "version",
                "created_at",
                "updated_at",
            },
        )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "realtime_admission_grants" not in tables:
        op.create_table(
            "realtime_admission_grants",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("room_id", sa.String(length=36), nullable=False),
            sa.Column("participant_id", sa.String(length=36), nullable=True),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("issued_by_id", sa.String(length=36), nullable=False),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column("grant_digest_sha256", sa.String(length=64), nullable=False),
            sa.Column("provider_token_jti_sha256", sa.String(length=64), nullable=True),
            sa.Column(
                "provider_adapter",
                sa.String(length=40),
                nullable=False,
                server_default="unassigned",
            ),
            sa.Column(
                "role",
                sa.String(length=32),
                nullable=False,
                server_default="attendee",
            ),
            sa.Column(
                "permissions",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="issued",
            ),
            sa.Column(
                "single_use", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "issued_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consumed_by_node", sa.String(length=160), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "expires_at > issued_at", name="ck_realtime_grant_expiry_after_issue"
            ),
            sa.ForeignKeyConstraint(
                ["issued_by_id", "organization_id"],
                ["users.id", "users.organization_id"],
                name="fk_realtime_grant_issuer_tenant",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["participant_id", "organization_id"],
                ["realtime_participants.id", "realtime_participants.organization_id"],
                name="fk_realtime_grant_participant_tenant",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["room_id", "organization_id"],
                ["realtime_rooms.id", "realtime_rooms.organization_id"],
                name="fk_realtime_grant_room_tenant",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id", "organization_id"],
                ["users.id", "users.organization_id"],
                name="fk_realtime_grant_user_tenant",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_realtime_grant_org_idempotency",
            ),
            sa.UniqueConstraint("grant_digest_sha256", name="uq_realtime_grant_digest"),
        )
        for name, columns in (
            ("ix_realtime_admission_grants_organization_id", ["organization_id"]),
            ("ix_realtime_admission_grants_room_id", ["room_id"]),
            ("ix_realtime_admission_grants_participant_id", ["participant_id"]),
            ("ix_realtime_admission_grants_user_id", ["user_id"]),
            ("ix_realtime_admission_grants_issued_by_id", ["issued_by_id"]),
            ("ix_realtime_admission_grants_status", ["status"]),
            ("ix_realtime_admission_grants_expires_at", ["expires_at"]),
            (
                "ix_realtime_grants_org_status_expires",
                ["organization_id", "status", "expires_at"],
            ),
            (
                "ix_realtime_grants_org_room_status",
                ["organization_id", "room_id", "status"],
            ),
            (
                "ix_realtime_grants_org_user_status",
                ["organization_id", "user_id", "status"],
            ),
        ):
            op.create_index(name, "realtime_admission_grants", columns)
    else:
        _assert_columns(
            inspector,
            "realtime_admission_grants",
            {
                "id",
                "organization_id",
                "room_id",
                "participant_id",
                "user_id",
                "issued_by_id",
                "idempotency_key",
                "grant_digest_sha256",
                "provider_token_jti_sha256",
                "provider_adapter",
                "role",
                "permissions",
                "status",
                "single_use",
                "issued_at",
                "expires_at",
                "consumed_at",
                "revoked_at",
                "consumed_by_node",
                "version",
                "created_at",
                "updated_at",
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table_name in (
        "realtime_admission_grants",
        "realtime_participants",
        "realtime_rooms",
        "realtime_tenant_quotas",
    ):
        if table_name in tables:
            op.drop_table(table_name)

    for table_name, constraint_name in (
        ("projects", "uq_project_id_org"),
        ("workspaces", "uq_workspace_id_org"),
        ("users", "uq_users_id_org"),
    ):
        inspector = sa.inspect(bind)
        names = {
            item.get("name")
            for item in inspector.get_unique_constraints(table_name)
            if item.get("name")
        }
        if constraint_name in names:
            op.drop_constraint(constraint_name, table_name, type_="unique")
