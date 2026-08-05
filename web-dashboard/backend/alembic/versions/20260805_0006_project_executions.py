"""Add durable single-server project execution jobs.

Revision ID: 20260805_0006
Revises: 20260802_0005
Create Date: 2026-08-05
"""

import sqlalchemy as sa
from alembic import op

revision = "20260805_0006"
down_revision = "20260802_0005"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind, table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(bind).get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    if "project_executions" not in _table_names(bind):
        op.create_table(
            "project_executions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("requested_by_id", sa.String(length=36), nullable=False),
            sa.Column("mode", sa.String(length=32), nullable=False),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("model", sa.String(length=160), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("stage", sa.String(length=64), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("external_processing_confirmed", sa.Boolean(), nullable=False),
            sa.Column("budget_cap_usd", sa.Float(), nullable=False),
            sa.Column("calculated_cost_usd", sa.Float(), nullable=True),
            sa.Column("requests_count", sa.Integer(), nullable=False),
            sa.Column("retries_count", sa.Integer(), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False),
            sa.Column("output_tokens", sa.Integer(), nullable=False),
            sa.Column("total_tokens", sa.Integer(), nullable=False),
            sa.Column("approved", sa.Boolean(), nullable=True),
            sa.Column("readiness_score", sa.Float(), nullable=True),
            sa.Column("result_summary", sa.JSON(), nullable=False),
            sa.Column("evidence_path", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(length=120), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("lease_token", sa.String(length=36), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["project_id"], ["projects.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["requested_by_id"], ["users.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = _index_names(bind, "project_executions")
    expected_indexes = {
        "ix_project_executions_organization_id": ["organization_id"],
        "ix_project_executions_workspace_id": ["workspace_id"],
        "ix_project_executions_project_id": ["project_id"],
        "ix_project_executions_requested_by_id": ["requested_by_id"],
        "ix_project_executions_status": ["status"],
        "ix_project_executions_org_status_created": [
            "organization_id",
            "status",
            "created_at",
        ],
        "ix_project_executions_project_created": ["project_id", "created_at"],
    }
    for name, columns in expected_indexes.items():
        if name not in indexes:
            op.create_index(name, "project_executions", columns, unique=False)

    if "uq_project_executions_active_project" not in _index_names(
        bind, "project_executions"
    ):
        op.create_index(
            "uq_project_executions_active_project",
            "project_executions",
            ["project_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('queued', 'running')"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "project_executions" in _table_names(bind):
        for name in sorted(_index_names(bind, "project_executions")):
            op.drop_index(name, table_name="project_executions")
        op.drop_table("project_executions")
