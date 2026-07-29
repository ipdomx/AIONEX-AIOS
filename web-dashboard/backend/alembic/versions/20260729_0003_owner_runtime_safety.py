"""Add Owner authentication generation and large backup size support.

Revision ID: 20260729_0003
Revises: 20260729_0002
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0003"
down_revision = "20260729_0002"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column(bind, table_name: str, column_name: str):
    return next(
        (
            column
            for column in sa.inspect(bind).get_columns(table_name)
            if column["name"] == column_name
        ),
        None,
    )


def upgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)

    if "users" in table_names and _column(bind, "users", "auth_version") is None:
        op.add_column(
            "users",
            sa.Column(
                "auth_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "backup_records" in table_names:
        size_bytes = _column(bind, "backup_records", "size_bytes")
        if size_bytes is not None and not isinstance(
            size_bytes["type"],
            sa.BigInteger,
        ):
            op.alter_column(
                "backup_records",
                "size_bytes",
                existing_type=size_bytes["type"],
                type_=sa.BigInteger(),
                existing_nullable=size_bytes["nullable"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)

    if "backup_records" in table_names:
        size_bytes = _column(bind, "backup_records", "size_bytes")
        if size_bytes is not None and isinstance(size_bytes["type"], sa.BigInteger):
            largest_backup = bind.execute(
                sa.text("SELECT max(size_bytes) FROM backup_records")
            ).scalar()
            if largest_backup is not None and largest_backup > 2_147_483_647:
                raise RuntimeError(
                    "Cannot downgrade backup_records.size_bytes to INTEGER while "
                    "a backup larger than 2 GiB is recorded"
                )
            op.alter_column(
                "backup_records",
                "size_bytes",
                existing_type=size_bytes["type"],
                type_=sa.Integer(),
                existing_nullable=size_bytes["nullable"],
            )

    if (
        "users" in table_names
        and _column(
            bind,
            "users",
            "auth_version",
        )
        is not None
    ):
        op.drop_column("users", "auth_version")
