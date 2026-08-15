"""Materialize existing GS-10 integration/report/team foundations.

Revision ID: 20260815_0024
Revises: 20260814_0023
"""

from alembic import op
import sqlalchemy as sa

revision = "20260815_0024"
down_revision = "20260814_0023"
branch_labels = None
depends_on = None

TABLES = {
    "growth_integration_connections",
    "growth_team_assignments",
    "growth_report_definitions",
    "growth_report_runs",
}


def _existing() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing()
    present = TABLES & existing
    if present == TABLES:
        return
    if present:
        raise RuntimeError(f"partial-gs10-schema:{sorted(present)}")

    op.create_table(
        "growth_integration_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("integration_type", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("credential_ref", sa.String(320)),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("last_simulated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "external_delivery_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "live_provider_call",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "integration_type",
            "name",
            name="uq_growth_integration_org_type_name",
        ),
    )
    op.create_index(
        "ix_growth_integrations_org_type_status",
        "growth_integration_connections",
        ["organization_id", "integration_type", "status"],
    )
    op.create_index(
        "ix_growth_integration_connections_organization_id",
        "growth_integration_connections",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_integration_connections_created_by_id",
        "growth_integration_connections",
        ["created_by_id"],
    )

    op.create_table(
        "growth_team_assignments",
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
        sa.Column(
            "team_id", sa.String(36), sa.ForeignKey("teams.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(40), nullable=False),
        sa.Column("scope_id", sa.String(160), nullable=False),
        sa.Column("role_key", sa.String(32), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column(
            "approval_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "scope_type",
            "scope_id",
            name="uq_growth_team_assignment_scope",
        ),
    )
    op.create_index(
        "ix_growth_team_assignments_org_scope_active",
        "growth_team_assignments",
        ["organization_id", "scope_type", "active"],
    )
    op.create_index(
        "ix_growth_team_assignments_organization_id",
        "growth_team_assignments",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_team_assignments_user_id", "growth_team_assignments", ["user_id"]
    )
    op.create_index(
        "ix_growth_team_assignments_team_id", "growth_team_assignments", ["team_id"]
    )
    op.create_index(
        "ix_growth_team_assignments_created_by_id",
        "growth_team_assignments",
        ["created_by_id"],
    )

    op.create_table(
        "growth_report_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("report_type", sa.String(40), nullable=False),
        sa.Column("formats", sa.JSON(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column(
            "schedule_kind", sa.String(24), nullable=False, server_default="manual"
        ),
        sa.Column("timezone_name", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("brand_name", sa.String(180)),
        sa.Column("custom_domain", sa.String(253)),
        sa.Column("branding", sa.JSON(), nullable=False),
        sa.Column(
            "external_delivery_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_growth_report_definition_org_name"
        ),
    )
    op.create_index(
        "ix_growth_report_definitions_org_schedule_active",
        "growth_report_definitions",
        ["organization_id", "schedule_kind", "active"],
    )
    op.create_index(
        "ix_growth_report_definitions_next_run",
        "growth_report_definitions",
        ["next_run_at"],
    )
    op.create_index(
        "ix_growth_report_definitions_organization_id",
        "growth_report_definitions",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_report_definitions_created_by_id",
        "growth_report_definitions",
        ["created_by_id"],
    )

    op.create_table(
        "growth_report_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "report_definition_id",
            sa.String(36),
            sa.ForeignKey("growth_report_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "triggered_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.Column("data_snapshot", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("artifact_manifest", sa.JSON(), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "external_delivery_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_report_runs_org_status_created",
        "growth_report_runs",
        ["organization_id", "status", "created_at"],
    )
    op.create_index(
        "ix_growth_report_runs_definition_created",
        "growth_report_runs",
        ["report_definition_id", "created_at"],
    )
    op.create_index(
        "ix_growth_report_runs_organization_id",
        "growth_report_runs",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_report_runs_report_definition_id",
        "growth_report_runs",
        ["report_definition_id"],
    )
    op.create_index(
        "ix_growth_report_runs_triggered_by_id",
        "growth_report_runs",
        ["triggered_by_id"],
    )


def downgrade() -> None:
    existing = _existing()
    for table in (
        "growth_report_runs",
        "growth_report_definitions",
        "growth_team_assignments",
        "growth_integration_connections",
    ):
        if table in existing:
            op.drop_table(table)
