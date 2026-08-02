"""Add verified social identities and WebAuthn passkey credentials.

Revision ID: 20260802_0005
Revises: 20260729_0004
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0005"
down_revision = "20260729_0004"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(bind).get_indexes(table_name)
        if index.get("name")
    }


def _unique_constraint_names(bind, table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints(table_name)
        if constraint.get("name")
    }


def _validate_table(
    bind,
    table_name: str,
    required_columns: set[str],
    required_unique_constraints: set[str],
) -> None:
    missing_columns = required_columns - _column_names(bind, table_name)
    if missing_columns:
        raise RuntimeError(
            f"Cannot migrate {table_name}: missing required columns: "
            f"{', '.join(sorted(missing_columns))}"
        )

    missing_constraints = required_unique_constraints - _unique_constraint_names(
        bind, table_name
    )
    if missing_constraints:
        raise RuntimeError(
            f"Cannot migrate {table_name}: missing required unique constraints: "
            f"{', '.join(sorted(missing_constraints))}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)

    if "external_identities" not in table_names:
        op.create_table(
            "external_identities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("provider", sa.String(length=80), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("provider_metadata", sa.JSON(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider", "subject", name="uq_external_identity_subject"
            ),
            sa.UniqueConstraint(
                "user_id", "provider", name="uq_external_identity_user_provider"
            ),
        )

    _validate_table(
        bind,
        "external_identities",
        {
            "id",
            "user_id",
            "provider",
            "subject",
            "email",
            "provider_metadata",
            "last_login_at",
            "created_at",
            "updated_at",
        },
        {
            "uq_external_identity_subject",
            "uq_external_identity_user_provider",
        },
    )
    external_identity_indexes = _index_names(bind, "external_identities")
    if "ix_external_identities_user_id" not in external_identity_indexes:
        op.create_index(
            "ix_external_identities_user_id",
            "external_identities",
            ["user_id"],
            unique=False,
        )
    if "ix_external_identity_user_provider" not in external_identity_indexes:
        op.create_index(
            "ix_external_identity_user_provider",
            "external_identities",
            ["user_id", "provider"],
            unique=False,
        )

    if "passkey_credentials" not in table_names:
        op.create_table(
            "passkey_credentials",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("credential_id", sa.String(length=1024), nullable=False),
            sa.Column("public_key", sa.Text(), nullable=False),
            sa.Column("sign_count", sa.BigInteger(), nullable=False),
            sa.Column("transports", sa.JSON(), nullable=False),
            sa.Column("aaguid", sa.String(length=64), nullable=True),
            sa.Column("device_type", sa.String(length=32), nullable=True),
            sa.Column("backed_up", sa.Boolean(), nullable=False),
            sa.Column("nickname", sa.String(length=120), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("credential_id", name="uq_passkey_credential_id"),
        )

    _validate_table(
        bind,
        "passkey_credentials",
        {
            "id",
            "user_id",
            "credential_id",
            "public_key",
            "sign_count",
            "transports",
            "aaguid",
            "device_type",
            "backed_up",
            "nickname",
            "last_used_at",
            "created_at",
            "updated_at",
        },
        {"uq_passkey_credential_id"},
    )
    passkey_indexes = _index_names(bind, "passkey_credentials")
    if "ix_passkey_credentials_user_id" not in passkey_indexes:
        op.create_index(
            "ix_passkey_credentials_user_id",
            "passkey_credentials",
            ["user_id"],
            unique=False,
        )
    if "ix_passkey_user_created" not in passkey_indexes:
        op.create_index(
            "ix_passkey_user_created",
            "passkey_credentials",
            ["user_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)

    if "passkey_credentials" in table_names:
        passkey_indexes = _index_names(bind, "passkey_credentials")
        if "ix_passkey_user_created" in passkey_indexes:
            op.drop_index("ix_passkey_user_created", table_name="passkey_credentials")
        if "ix_passkey_credentials_user_id" in passkey_indexes:
            op.drop_index(
                "ix_passkey_credentials_user_id",
                table_name="passkey_credentials",
            )
        op.drop_table("passkey_credentials")

    if "external_identities" in table_names:
        external_identity_indexes = _index_names(bind, "external_identities")
        if "ix_external_identity_user_provider" in external_identity_indexes:
            op.drop_index(
                "ix_external_identity_user_provider",
                table_name="external_identities",
            )
        if "ix_external_identities_user_id" in external_identity_indexes:
            op.drop_index(
                "ix_external_identities_user_id",
                table_name="external_identities",
            )
        op.drop_table("external_identities")
