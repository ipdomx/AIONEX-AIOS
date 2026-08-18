"""Add Phase 36E durable design image execution authority.

Revision ID: 20260818_0032
Revises: 20260817_0031
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260818_0032"
down_revision = "20260817_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required_tables = {
        "organizations", "users", "media_asset_graphs", "media_asset_nodes",
    }
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        raise RuntimeError(
            "Phase 36E design image migration requires tables: " + ", ".join(missing_tables)
        )

    if "design_image_executions" not in tables:
        op.create_table(
            "design_image_executions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="SET NULL")),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
            sa.Column("studio_job_id", sa.String(36), sa.ForeignKey("studio_jobs.id", ondelete="SET NULL")),
            sa.Column("studio_asset_id", sa.String(36), sa.ForeignKey("studio_assets.id", ondelete="SET NULL")),
            sa.Column("graph_id", sa.String(36), sa.ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_node_id", sa.String(36), sa.ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("operation", sa.String(40), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(160), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("prompt_sha256", sa.String(64), nullable=False),
            sa.Column("request_options", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("output_format", sa.String(16), nullable=False, server_default="png"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("lease_owner", sa.String(160)),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("available_at", sa.DateTime(timezone=True)),
            sa.Column("provider_request_id", sa.String(200)),
            sa.Column("provider_response_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("usage_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("actual_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("output_storage_backend", sa.String(32)),
            sa.Column("output_storage_key", sa.Text()),
            sa.Column("output_checksum", sa.String(64)),
            sa.Column("output_size_bytes", sa.BigInteger()),
            sa.Column("error_code", sa.String(120)),
            sa.Column("error_message", sa.Text()),
            sa.Column("armed_at", sa.DateTime(timezone=True)),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "organization_id", "idempotency_key",
                name="uq_design_image_execution_org_idempotency",
            ),
        )
    else:
        required_columns = {
            "id", "organization_id", "graph_id", "target_node_id", "requested_by_id",
            "operation", "provider", "model", "status", "idempotency_key",
            "prompt_sha256", "request_options", "output_format", "attempts", "max_attempts",
            "lease_token", "lease_owner", "lease_expires_at", "fencing_token", "available_at",
            "provider_request_id", "provider_response_metadata", "usage_metadata",
            "estimated_cost_usd", "actual_cost_usd", "output_storage_backend",
            "output_storage_key", "output_checksum", "output_size_bytes", "armed_at",
            "started_at", "completed_at", "created_at", "updated_at",
        }
        existing_columns = {item["name"] for item in inspector.get_columns("design_image_executions")}
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            raise RuntimeError(
                "Existing design_image_executions table is incomplete: " + ", ".join(missing_columns)
            )

    existing_indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("design_image_executions")
    }
    for name, fields in (
        ("ix_design_image_executions_organization_id", ["organization_id"]),
        ("ix_design_image_executions_workspace_id", ["workspace_id"]),
        ("ix_design_image_executions_project_id", ["project_id"]),
        ("ix_design_image_executions_studio_job_id", ["studio_job_id"]),
        ("ix_design_image_executions_studio_asset_id", ["studio_asset_id"]),
        ("ix_design_image_executions_graph_id", ["graph_id"]),
        ("ix_design_image_executions_target_node_id", ["target_node_id"]),
        ("ix_design_image_executions_requested_by_id", ["requested_by_id"]),
        ("ix_design_image_executions_operation", ["operation"]),
        ("ix_design_image_executions_provider", ["provider"]),
        ("ix_design_image_executions_status", ["status"]),
        ("ix_design_image_executions_prompt_sha256", ["prompt_sha256"]),
        ("ix_design_image_executions_lease_owner", ["lease_owner"]),
        ("ix_design_image_executions_lease_expires_at", ["lease_expires_at"]),
        ("ix_design_image_executions_available_at", ["available_at"]),
        ("ix_design_image_executions_provider_request_id", ["provider_request_id"]),
        ("ix_design_image_executions_output_checksum", ["output_checksum"]),
        ("ix_design_image_executions_org_status_created", ["organization_id", "status", "created_at"]),
        ("ix_design_image_executions_claim", ["status", "available_at", "created_at"]),
        ("ix_design_image_executions_graph_status", ["graph_id", "status"]),
    ):
        if name not in existing_indexes:
            op.create_index(name, "design_image_executions", fields)


def downgrade() -> None:
    op.drop_table("design_image_executions")
