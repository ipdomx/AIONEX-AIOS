"""Add durable Owner Dashboard control-plane records.

Revision ID: 20260729_0002
Revises: 20260726_0001
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0002"
down_revision = "20260726_0001"
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


def _column(bind, table_name: str, column_name: str):
    return next(
        (
            column
            for column in sa.inspect(bind).get_columns(table_name)
            if column["name"] == column_name
        ),
        None,
    )


def _foreign_keys_for_column(bind, table_name: str, column_name: str) -> set[str]:
    return {
        foreign_key["name"]
        for foreign_key in sa.inspect(bind).get_foreign_keys(table_name)
        if foreign_key.get("name")
        and column_name in foreign_key.get("constrained_columns", [])
    }


def upgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)

    if "roles" in table_names:
        role_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("roles")
        }
        if "status" not in role_columns:
            op.add_column(
                "roles",
                sa.Column(
                    "status",
                    sa.String(length=32),
                    nullable=False,
                    server_default="active",
                ),
            )
        role_indexes = _index_names(bind, "roles")
        if "ix_roles_status" not in role_indexes:
            op.create_index("ix_roles_status", "roles", ["status"])

    if "audit_events" in table_names:
        resource_id = _column(bind, "audit_events", "resource_id")
        resource_id_length = (
            getattr(resource_id["type"], "length", None) if resource_id else None
        )
        if resource_id is not None and (
            resource_id_length is None or resource_id_length < 160
        ):
            op.alter_column(
                "audit_events",
                "resource_id",
                existing_type=resource_id["type"],
                type_=sa.String(length=160),
                existing_nullable=resource_id["nullable"],
            )

    if "meetings" in table_names:
        meeting_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("meetings")
        }
        if "workspace_id" not in meeting_columns:
            op.add_column(
                "meetings",
                sa.Column("workspace_id", sa.String(length=36), nullable=True),
            )
        if not _foreign_keys_for_column(bind, "meetings", "workspace_id"):
            op.create_foreign_key(
                "fk_meetings_workspace_id_workspaces",
                "meetings",
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "attendee_ids" not in meeting_columns:
            op.add_column(
                "meetings",
                sa.Column(
                    "attendee_ids",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'::json"),
                ),
            )
        meeting_indexes = _index_names(bind, "meetings")
        if "ix_meetings_workspace_id" not in meeting_indexes:
            op.create_index(
                "ix_meetings_workspace_id",
                "meetings",
                ["workspace_id"],
            )

    if "workflows" in table_names:
        workflow_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("workflows")
        }
        if "workspace_id" not in workflow_columns:
            op.add_column(
                "workflows",
                sa.Column("workspace_id", sa.String(length=36), nullable=True),
            )
        if not _foreign_keys_for_column(bind, "workflows", "workspace_id"):
            op.create_foreign_key(
                "fk_workflows_workspace_id_workspaces",
                "workflows",
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="SET NULL",
            )
        bind.execute(sa.text("""
                UPDATE workflows
                SET workspace_id = projects.workspace_id
                FROM projects
                WHERE workflows.project_id = projects.id
                  AND workflows.workspace_id IS NULL
                """))
        if "ix_workflows_workspace_id" not in _index_names(bind, "workflows"):
            op.create_index(
                "ix_workflows_workspace_id",
                "workflows",
                ["workspace_id"],
            )

    if "owner_control_records" not in table_names:
        op.create_table(
            "owner_control_records",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("domain", sa.String(length=80), nullable=False),
            sa.Column("resource_id", sa.String(length=160), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "domain",
                "resource_id",
                name="uq_owner_control_domain_resource",
            ),
        )

    owner_control_indexes = _index_names(bind, "owner_control_records")
    if "ix_owner_control_records_domain" not in owner_control_indexes:
        op.create_index(
            "ix_owner_control_records_domain",
            "owner_control_records",
            ["domain"],
        )
    if "ix_owner_control_domain_status" not in owner_control_indexes:
        op.create_index(
            "ix_owner_control_domain_status",
            "owner_control_records",
            ["domain", "status"],
        )

    if "owner_command_records" not in table_names:
        op.create_table(
            "owner_command_records",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("actor_id", sa.String(length=36), nullable=True),
            sa.Column("domain", sa.String(length=80), nullable=False),
            sa.Column("resource_id", sa.String(length=160), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="accepted",
            ),
            sa.Column("request", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["actor_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    owner_command_indexes = _index_names(bind, "owner_command_records")
    if "ix_owner_command_records_actor_id" not in owner_command_indexes:
        op.create_index(
            "ix_owner_command_records_actor_id",
            "owner_command_records",
            ["actor_id"],
        )
    if "ix_owner_command_records_created_at" not in owner_command_indexes:
        op.create_index(
            "ix_owner_command_records_created_at",
            "owner_command_records",
            ["created_at"],
        )
    if "ix_owner_command_domain_created" not in owner_command_indexes:
        op.create_index(
            "ix_owner_command_domain_created",
            "owner_command_records",
            ["domain", "created_at"],
        )
    if "ix_owner_command_status_created" not in owner_command_indexes:
        op.create_index(
            "ix_owner_command_status_created",
            "owner_command_records",
            ["status", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)

    if "owner_command_records" in table_names:
        owner_command_indexes = _index_names(bind, "owner_command_records")
        for index_name in (
            "ix_owner_command_status_created",
            "ix_owner_command_domain_created",
            "ix_owner_command_records_created_at",
            "ix_owner_command_records_actor_id",
        ):
            if index_name in owner_command_indexes:
                op.drop_index(index_name, table_name="owner_command_records")
        op.drop_table("owner_command_records")

    if "owner_control_records" in table_names:
        owner_control_indexes = _index_names(bind, "owner_control_records")
        for index_name in (
            "ix_owner_control_domain_status",
            "ix_owner_control_records_domain",
        ):
            if index_name in owner_control_indexes:
                op.drop_index(index_name, table_name="owner_control_records")
        op.drop_table("owner_control_records")

    if "meetings" in table_names:
        meeting_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("meetings")
        }
        if (
            "workspace_id" in meeting_columns
            and "ix_meetings_workspace_id" in _index_names(bind, "meetings")
        ):
            op.drop_index("ix_meetings_workspace_id", table_name="meetings")
        if "attendee_ids" in meeting_columns:
            op.drop_column("meetings", "attendee_ids")
        if "workspace_id" in meeting_columns:
            for foreign_key_name in _foreign_keys_for_column(
                bind, "meetings", "workspace_id"
            ):
                op.drop_constraint(
                    foreign_key_name,
                    "meetings",
                    type_="foreignkey",
                )
            op.drop_column("meetings", "workspace_id")

    if "workflows" in table_names:
        workflow_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("workflows")
        }
        if (
            "workspace_id" in workflow_columns
            and "ix_workflows_workspace_id" in _index_names(bind, "workflows")
        ):
            op.drop_index("ix_workflows_workspace_id", table_name="workflows")
        if "workspace_id" in workflow_columns:
            for foreign_key_name in _foreign_keys_for_column(
                bind, "workflows", "workspace_id"
            ):
                op.drop_constraint(
                    foreign_key_name,
                    "workflows",
                    type_="foreignkey",
                )
            op.drop_column("workflows", "workspace_id")

    if "roles" in table_names:
        role_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("roles")
        }
        if "status" in role_columns:
            if "ix_roles_status" in _index_names(bind, "roles"):
                op.drop_index("ix_roles_status", table_name="roles")
            op.drop_column("roles", "status")

    if "audit_events" in table_names:
        resource_id = _column(bind, "audit_events", "resource_id")
        resource_id_length = (
            getattr(resource_id["type"], "length", None) if resource_id else None
        )
        if resource_id is not None and (
            resource_id_length is None or resource_id_length > 120
        ):
            longest_resource_id = bind.execute(
                sa.text("SELECT max(char_length(resource_id)) FROM audit_events")
            ).scalar()
            if longest_resource_id is not None and longest_resource_id > 120:
                raise RuntimeError(
                    "Cannot downgrade audit_events.resource_id to 120 characters "
                    "while longer values exist"
                )
            op.alter_column(
                "audit_events",
                "resource_id",
                existing_type=resource_id["type"],
                type_=sa.String(length=120),
                existing_nullable=resource_id["nullable"],
            )
