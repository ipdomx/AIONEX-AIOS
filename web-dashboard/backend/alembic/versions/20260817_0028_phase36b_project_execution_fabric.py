"""Add Phase 36B distributed live project-execution control fields.

Revision ID: 20260817_0028
Revises: 20260816_0027
"""

from alembic import op
import sqlalchemy as sa

revision = "20260817_0028"
down_revision = "20260816_0027"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_indexes(table)
        if item.get("name")
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "project_executions" not in tables:
        raise RuntimeError("project_executions table is required before Phase 36B migration")

    columns = _columns("project_executions")
    additions = (
        ("lease_owner", sa.Column("lease_owner", sa.String(160))),
        ("lease_expires_at", sa.Column("lease_expires_at", sa.DateTime(timezone=True))),
        (
            "fencing_token",
            sa.Column(
                "fencing_token",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "resource_class",
            sa.Column(
                "resource_class",
                sa.String(64),
                nullable=False,
                server_default="project-build-cpu",
            ),
        ),
        (
            "priority_rank",
            sa.Column(
                "priority_rank",
                sa.Integer(),
                nullable=False,
                server_default="100",
            ),
        ),
        ("available_at", sa.Column("available_at", sa.DateTime(timezone=True))),
        ("dead_lettered_at", sa.Column("dead_lettered_at", sa.DateTime(timezone=True))),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("project_executions", column)

    indexes = _indexes("project_executions")
    index_specs = (
        ("ix_project_executions_lease_owner", ["lease_owner"]),
        ("ix_project_executions_lease_expires_at", ["lease_expires_at"]),
        ("ix_project_executions_resource_class", ["resource_class"]),
        ("ix_project_executions_available_at", ["available_at"]),
        ("ix_project_executions_dead_lettered_at", ["dead_lettered_at"]),
        (
            "ix_project_executions_dispatch_queue",
            ["status", "resource_class", "priority_rank", "available_at", "created_at"],
        ),
        (
            "ix_project_executions_lease_recovery",
            ["status", "lease_expires_at"],
        ),
    )
    for name, fields in index_specs:
        if name not in indexes:
            op.create_index(name, "project_executions", fields)

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "project_execution_workers" not in tables:
        op.create_table(
            "project_execution_workers",
            sa.Column("id", sa.String(160), primary_key=True),
            sa.Column("resource_classes", sa.JSON(), nullable=False),
            sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("active_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(32), nullable=False, server_default="online"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_project_execution_workers_status",
            "project_execution_workers",
            ["status"],
        )
        op.create_index(
            "ix_project_execution_workers_last_heartbeat_at",
            "project_execution_workers",
            ["last_heartbeat_at"],
        )
        op.create_index(
            "ix_project_execution_workers_status_heartbeat",
            "project_execution_workers",
            ["status", "last_heartbeat_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "project_execution_workers" in tables:
        op.drop_table("project_execution_workers")

    if "project_executions" not in tables:
        return
    indexes = _indexes("project_executions")
    for name in (
        "ix_project_executions_lease_recovery",
        "ix_project_executions_dispatch_queue",
        "ix_project_executions_dead_lettered_at",
        "ix_project_executions_available_at",
        "ix_project_executions_resource_class",
        "ix_project_executions_lease_expires_at",
        "ix_project_executions_lease_owner",
    ):
        if name in indexes:
            op.drop_index(name, table_name="project_executions")

    columns = _columns("project_executions")
    for name in (
        "dead_lettered_at",
        "available_at",
        "priority_rank",
        "resource_class",
        "fencing_token",
        "lease_expires_at",
        "lease_owner",
    ):
        if name in columns:
            op.drop_column("project_executions", name)
