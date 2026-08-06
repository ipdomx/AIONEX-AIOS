"""Complete projects, workforce, academy, and knowledge persistence.

Revision ID: 20260807_0010
Revises: 20260806_0009
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.db import models  # noqa: F401
from app.db.base import Base

revision = "20260807_0010"
down_revision = "20260806_0009"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "academy_courses",
    "workforce_members",
    "academy_enrollments",
    "knowledge_items",
    "project_events",
    "project_memberships",
    "workforce_health_reports",
    "academy_assessments",
    "knowledge_provenance",
    "scoped_memories",
    "task_comments",
    "workflow_runs",
    "workforce_assignments",
    "academy_certifications",
    "learning_events",
    "workforce_incidents",
    "workforce_performance_events",
    "lessons",
)


def _inspector():
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {item["name"] for item in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {str(item["name"]) for item in _inspector().get_indexes(table)}


def _foreign_keys(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {
        str(item["name"])
        for item in _inspector().get_foreign_keys(table)
        if item.get("name")
    }


def _add_column(table: str, column: sa.Column) -> None:
    if table in _tables() and column.name not in _columns(table):
        op.add_column(table, column)


def _create_index(name: str, table: str, columns: list[str]) -> None:
    if table in _tables() and name not in _indexes(table):
        op.create_index(name, table, columns, unique=False)


def _create_fk(
    name: str,
    source: str,
    target: str,
    local: list[str],
    remote: list[str],
) -> None:
    if source in _tables() and name not in _foreign_keys(source):
        op.create_foreign_key(
            name,
            source,
            target,
            local,
            remote,
            ondelete="SET NULL",
        )


def upgrade() -> None:
    bind = op.get_bind()
    metadata = Base.metadata
    for table_name in NEW_TABLES:
        metadata.tables[table_name].create(bind=bind, checkfirst=True)

    _add_column(
        "projects",
        sa.Column("risk", sa.String(32), nullable=False, server_default="normal"),
    )
    _add_column(
        "projects",
        sa.Column(
            "review_status",
            sa.String(32),
            nullable=False,
            server_default="not_requested",
        ),
    )
    _add_column("projects", sa.Column("approved_by_id", sa.String(36)))
    _add_column("projects", sa.Column("approved_at", sa.DateTime(timezone=True)))
    _add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True)))
    _add_column("projects", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    _add_column("projects", sa.Column("completed_at", sa.DateTime(timezone=True)))
    _add_column(
        "projects",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    _create_index("ix_projects_approved_by_id", "projects", ["approved_by_id"])
    _create_fk(
        "fk_projects_approved_by_id_users",
        "projects",
        "users",
        ["approved_by_id"],
        ["id"],
    )

    _add_column(
        "tasks",
        sa.Column(
            "review_status",
            sa.String(32),
            nullable=False,
            server_default="not_requested",
        ),
    )
    _add_column(
        "tasks",
        sa.Column("rework_count", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column("tasks", sa.Column("completed_at", sa.DateTime(timezone=True)))
    _add_column("tasks", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    _add_column(
        "tasks",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    _add_column("workflows", sa.Column("archived_at", sa.DateTime(timezone=True)))
    _add_column(
        "workflows",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    _add_column("reports", sa.Column("workspace_id", sa.String(36)))
    _add_column("reports", sa.Column("generated_by_id", sa.String(36)))
    _add_column(
        "reports",
        sa.Column("format", sa.String(32), nullable=False, server_default="json"),
    )
    _add_column(
        "reports",
        sa.Column(
            "content",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    _add_column("reports", sa.Column("checksum", sa.String(64)))
    _add_column("reports", sa.Column("size_bytes", sa.BigInteger()))
    _add_column("reports", sa.Column("archived_at", sa.DateTime(timezone=True)))
    _add_column(
        "reports",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    _create_index("ix_reports_workspace_id", "reports", ["workspace_id"])
    _create_index("ix_reports_generated_by_id", "reports", ["generated_by_id"])
    _create_fk(
        "fk_reports_workspace_id_workspaces",
        "reports",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    _create_fk(
        "fk_reports_generated_by_id_users",
        "reports",
        "users",
        ["generated_by_id"],
        ["id"],
    )

    _add_column(
        "project_executions",
        sa.Column(
            "review_status",
            sa.String(32),
            nullable=False,
            server_default="not_requested",
        ),
    )
    _add_column(
        "project_executions",
        sa.Column("rework_count", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column(
        "project_executions", sa.Column("paused_at", sa.DateTime(timezone=True))
    )
    _add_column(
        "project_executions", sa.Column("cancelled_at", sa.DateTime(timezone=True))
    )
    _add_column(
        "project_executions",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    if "project_executions" in _tables():
        for column in (
            "version",
            "cancelled_at",
            "paused_at",
            "rework_count",
            "review_status",
        ):
            if column in _columns("project_executions"):
                op.drop_column("project_executions", column)

    if "reports" in _tables():
        for constraint in (
            "fk_reports_generated_by_id_users",
            "fk_reports_workspace_id_workspaces",
        ):
            if constraint in _foreign_keys("reports"):
                op.drop_constraint(constraint, "reports", type_="foreignkey")
        for index in ("ix_reports_generated_by_id", "ix_reports_workspace_id"):
            if index in _indexes("reports"):
                op.drop_index(index, table_name="reports")
        for column in (
            "version",
            "archived_at",
            "size_bytes",
            "checksum",
            "content",
            "format",
            "generated_by_id",
            "workspace_id",
        ):
            if column in _columns("reports"):
                op.drop_column("reports", column)

    if "workflows" in _tables():
        for column in ("version", "archived_at"):
            if column in _columns("workflows"):
                op.drop_column("workflows", column)

    if "tasks" in _tables():
        for column in (
            "version",
            "cancelled_at",
            "completed_at",
            "rework_count",
            "review_status",
        ):
            if column in _columns("tasks"):
                op.drop_column("tasks", column)

    if "projects" in _tables():
        if "fk_projects_approved_by_id_users" in _foreign_keys("projects"):
            op.drop_constraint(
                "fk_projects_approved_by_id_users",
                "projects",
                type_="foreignkey",
            )
        if "ix_projects_approved_by_id" in _indexes("projects"):
            op.drop_index("ix_projects_approved_by_id", table_name="projects")
        for column in (
            "version",
            "completed_at",
            "cancelled_at",
            "archived_at",
            "approved_at",
            "approved_by_id",
            "review_status",
            "risk",
        ):
            if column in _columns("projects"):
                op.drop_column("projects", column)

    for table_name in reversed(NEW_TABLES):
        if table_name in _tables():
            op.drop_table(table_name)
