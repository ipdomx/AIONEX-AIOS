"""Add durable fencing tokens to backup worker jobs.

Revision ID: 20260729_0004
Revises: 20260729_0003
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0004"
down_revision = "20260729_0003"
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


def _validate_lease_column(table_name: str, column) -> None:
    column_type = column["type"]
    if (
        not isinstance(column_type, sa.String)
        or getattr(column_type, "length", None) != 36
        or column["nullable"] is not True
    ):
        raise RuntimeError(f"{table_name}.lease_token must be nullable VARCHAR(36)")


def upgrade() -> None:
    bind = op.get_bind()
    required_tables = {"backup_records", "disaster_recovery_runs"}
    missing_tables = required_tables - _table_names(bind)
    if missing_tables:
        raise RuntimeError(
            "Cannot add durable backup job leases because required tables are "
            f"missing: {', '.join(sorted(missing_tables))}"
        )

    for table_name in sorted(required_tables):
        lease_token = _column(bind, table_name, "lease_token")
        if lease_token is None:
            op.add_column(
                table_name,
                sa.Column("lease_token", sa.String(length=36), nullable=True),
            )
            lease_token = _column(bind, table_name, "lease_token")
        _validate_lease_column(table_name, lease_token)


def downgrade() -> None:
    bind = op.get_bind()
    tables_with_lease = [
        table_name
        for table_name in ("disaster_recovery_runs", "backup_records")
        if table_name in _table_names(bind)
        and _column(bind, table_name, "lease_token") is not None
    ]
    for table_name in tables_with_lease:
        active_job = bind.execute(
            sa.text(f"SELECT 1 FROM {table_name} " "WHERE status = 'running' LIMIT 1")
        ).first()
        if active_job is not None:
            raise RuntimeError(
                "Cannot remove durable backup job leases while jobs are running"
            )
    for table_name in tables_with_lease:
        op.drop_column(table_name, "lease_token")
