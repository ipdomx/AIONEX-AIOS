"""Add Phase 36C durable Project AI routing authority records.

Revision ID: 20260817_0029
Revises: 20260817_0028
"""

from alembic import op
import sqlalchemy as sa

revision = "20260817_0029"
down_revision = "20260817_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    required = {
        "organizations",
        "workspaces",
        "projects",
        "project_executions",
        "ai_providers",
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "Phase 36C routing migration requires tables: " + ", ".join(missing)
        )

    if "project_ai_route_plans" not in tables:
        op.create_table(
            "project_ai_route_plans",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "workspace_id",
                sa.String(36),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "execution_id",
                sa.String(36),
                sa.ForeignKey("project_executions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("plan_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("policy", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column(
                "total_primary_estimated_microusd",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "execution_id",
                "plan_version",
                name="uq_project_ai_route_plan_execution_version",
            ),
        )
        op.create_index(
            "ix_project_ai_route_plans_organization_id",
            "project_ai_route_plans",
            ["organization_id"],
        )
        op.create_index(
            "ix_project_ai_route_plans_workspace_id",
            "project_ai_route_plans",
            ["workspace_id"],
        )
        op.create_index(
            "ix_project_ai_route_plans_project_id",
            "project_ai_route_plans",
            ["project_id"],
        )
        op.create_index(
            "ix_project_ai_route_plans_execution_id",
            "project_ai_route_plans",
            ["execution_id"],
        )
        op.create_index(
            "ix_project_ai_route_plans_status",
            "project_ai_route_plans",
            ["status"],
        )
        op.create_index(
            "ix_project_ai_route_plans_org_status_created",
            "project_ai_route_plans",
            ["organization_id", "status", "created_at"],
        )
        op.create_index(
            "ix_project_ai_route_plans_project_created",
            "project_ai_route_plans",
            ["project_id", "created_at"],
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "project_ai_route_tasks" not in tables:
        op.create_table(
            "project_ai_route_tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "plan_id",
                sa.String(36),
                sa.ForeignKey("project_ai_route_plans.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("task_id", sa.String(160), nullable=False),
            sa.Column("role", sa.String(64), nullable=False),
            sa.Column("task", sa.String(80), nullable=False),
            sa.Column(
                "primary_provider_id",
                sa.String(36),
                sa.ForeignKey("ai_providers.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("primary_provider_type", sa.String(64), nullable=False),
            sa.Column("primary_model", sa.String(160), nullable=False),
            sa.Column("candidates", sa.JSON(), nullable=False),
            sa.Column("estimated_microusd", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column(
                "selected_provider_id",
                sa.String(36),
                sa.ForeignKey("ai_providers.id", ondelete="RESTRICT"),
            ),
            sa.Column("selected_provider_type", sa.String(64)),
            sa.Column("selected_model", sa.String(160)),
            sa.Column("evidence_ref", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "plan_id", "task_id", name="uq_project_ai_route_task_plan_task"
            ),
        )
        for name, fields in (
            ("ix_project_ai_route_tasks_plan_id", ["plan_id"]),
            ("ix_project_ai_route_tasks_organization_id", ["organization_id"]),
            ("ix_project_ai_route_tasks_primary_provider_id", ["primary_provider_id"]),
            ("ix_project_ai_route_tasks_selected_provider_id", ["selected_provider_id"]),
            ("ix_project_ai_route_tasks_status", ["status"]),
            ("ix_project_ai_route_tasks_org_status", ["organization_id", "status"]),
        ):
            op.create_index(name, "project_ai_route_tasks", fields)

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "project_ai_route_attempts" not in tables:
        op.create_table(
            "project_ai_route_attempts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "task_route_id",
                sa.String(36),
                sa.ForeignKey("project_ai_route_tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "execution_id",
                sa.String(36),
                sa.ForeignKey("project_executions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "provider_id",
                sa.String(36),
                sa.ForeignKey("ai_providers.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("provider_type", sa.String(64), nullable=False),
            sa.Column("model", sa.String(160), nullable=False),
            sa.Column("attempt_index", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="reserved"),
            sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("estimated_microusd", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("reserved_microusd", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("actual_microusd", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
            sa.Column("error_code", sa.String(120)),
            sa.Column("evidence_ref", sa.Text()),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "task_route_id",
                "attempt_index",
                name="uq_project_ai_route_attempt_task_index",
            ),
        )
        for name, fields in (
            ("ix_project_ai_route_attempts_task_route_id", ["task_route_id"]),
            ("ix_project_ai_route_attempts_organization_id", ["organization_id"]),
            ("ix_project_ai_route_attempts_execution_id", ["execution_id"]),
            ("ix_project_ai_route_attempts_provider_id", ["provider_id"]),
            ("ix_project_ai_route_attempts_status", ["status"]),
            (
                "ix_project_ai_route_attempts_org_status_created",
                ["organization_id", "status", "created_at"],
            ),
            (
                "ix_project_ai_route_attempts_provider_status",
                ["provider_id", "status"],
            ),
        ):
            op.create_index(name, "project_ai_route_attempts", fields)

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "project_ai_execution_budgets" not in tables:
        op.create_table(
            "project_ai_execution_budgets",
            sa.Column(
                "execution_id",
                sa.String(36),
                sa.ForeignKey("project_executions.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("limit_microusd", sa.BigInteger(), nullable=False),
            sa.Column("reserved_microusd", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("spent_microusd", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_project_ai_execution_budgets_organization_id",
            "project_ai_execution_budgets",
            ["organization_id"],
        )
        op.create_index(
            "ix_project_ai_execution_budgets_org",
            "project_ai_execution_budgets",
            ["organization_id"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (
        "project_ai_route_attempts",
        "project_ai_route_tasks",
        "project_ai_execution_budgets",
        "project_ai_route_plans",
    ):
        if table in tables:
            op.drop_table(table)
