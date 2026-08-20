"""Add Phase 36F durable video execution and scene authority.

Revision ID: 20260819_0034
Revises: 20260818_0033
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260819_0034"
down_revision = "20260818_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required_tables = {
        "organizations",
        "users",
        "media_asset_graphs",
        "media_asset_nodes",
    }
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        raise RuntimeError(
            "Phase 36F video migration requires tables: " + ", ".join(missing_tables)
        )

    if "video_executions" not in tables:
        op.create_table(
            "video_executions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="SET NULL")),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
            sa.Column("studio_job_id", sa.String(36), sa.ForeignKey("studio_jobs.id", ondelete="SET NULL")),
            sa.Column("studio_asset_id", sa.String(36), sa.ForeignKey("studio_assets.id", ondelete="SET NULL")),
            sa.Column("graph_id", sa.String(36), sa.ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(160), nullable=False),
            sa.Column("operation", sa.String(40), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("plan_sha256", sa.String(64), nullable=False),
            sa.Column("continuity_id", sa.String(64), nullable=False),
            sa.Column("plan_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("request_options", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("scene_count", sa.Integer(), nullable=False),
            sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("actual_cost_usd", sa.Float(), nullable=True),
            sa.Column("cost_basis", sa.String(64), nullable=False, server_default="unknown"),
            sa.Column("final_storage_backend", sa.String(32)),
            sa.Column("final_storage_key", sa.Text()),
            sa.Column("final_checksum", sa.String(64)),
            sa.Column("final_size_bytes", sa.BigInteger()),
            sa.Column("final_media_type", sa.String(120)),
            sa.Column("error_code", sa.String(120)),
            sa.Column("error_message", sa.Text()),
            sa.Column("armed_at", sa.DateTime(timezone=True)),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "organization_id", "idempotency_key", name="uq_video_execution_org_idempotency"
            ),
        )

    if "video_scene_executions" not in tables:
        op.create_table(
            "video_scene_executions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("video_execution_id", sa.String(36), sa.ForeignKey("video_executions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("graph_id", sa.String(36), sa.ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_node_id", sa.String(36), sa.ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("scene_key", sa.String(80), nullable=False),
            sa.Column("scene_index", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(160), nullable=False),
            sa.Column("operation", sa.String(40), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("prompt_sha256", sa.String(64), nullable=False),
            sa.Column("request_options", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_polls", sa.Integer(), nullable=False, server_default="360"),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("lease_owner", sa.String(160)),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("available_at", sa.DateTime(timezone=True)),
            sa.Column("provider_request_id", sa.String(240)),
            sa.Column("provider_state", sa.String(40), nullable=False, server_default="not_started"),
            sa.Column("provider_progress", sa.Integer()),
            sa.Column("provider_response_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("usage_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("actual_cost_usd", sa.Float(), nullable=True),
            sa.Column("cost_basis", sa.String(64), nullable=False, server_default="unknown"),
            sa.Column("output_storage_backend", sa.String(32)),
            sa.Column("output_storage_key", sa.Text()),
            sa.Column("output_checksum", sa.String(64)),
            sa.Column("output_size_bytes", sa.BigInteger()),
            sa.Column("output_media_type", sa.String(120)),
            sa.Column("error_code", sa.String(120)),
            sa.Column("error_message", sa.Text()),
            sa.Column("provider_submitted_at", sa.DateTime(timezone=True)),
            sa.Column("last_polled_at", sa.DateTime(timezone=True)),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "video_execution_id", "scene_key", name="uq_video_scene_execution_scene"
            ),
            sa.UniqueConstraint(
                "organization_id", "idempotency_key", name="uq_video_scene_execution_org_idempotency"
            ),
            sa.UniqueConstraint(
                "provider", "provider_request_id", name="uq_video_scene_execution_provider_job"
            ),
        )

    inspector = sa.inspect(bind)
    video_indexes = {item["name"] for item in inspector.get_indexes("video_executions")}
    for name, fields in (
        ("ix_video_executions_organization_id", ["organization_id"]),
        ("ix_video_executions_workspace_id", ["workspace_id"]),
        ("ix_video_executions_project_id", ["project_id"]),
        ("ix_video_executions_studio_job_id", ["studio_job_id"]),
        ("ix_video_executions_studio_asset_id", ["studio_asset_id"]),
        ("ix_video_executions_graph_id", ["graph_id"]),
        ("ix_video_executions_requested_by_id", ["requested_by_id"]),
        ("ix_video_executions_provider", ["provider"]),
        ("ix_video_executions_status", ["status"]),
        ("ix_video_executions_plan_sha256", ["plan_sha256"]),
        ("ix_video_executions_continuity_id", ["continuity_id"]),
        ("ix_video_executions_final_checksum", ["final_checksum"]),
        ("ix_video_executions_org_status_created", ["organization_id", "status", "created_at"]),
        ("ix_video_executions_graph_status", ["graph_id", "status"]),
    ):
        if name not in video_indexes:
            op.create_index(name, "video_executions", fields)

    scene_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("video_scene_executions")}
    for name, fields in (
        ("ix_video_scene_executions_video_execution_id", ["video_execution_id"]),
        ("ix_video_scene_executions_organization_id", ["organization_id"]),
        ("ix_video_scene_executions_graph_id", ["graph_id"]),
        ("ix_video_scene_executions_target_node_id", ["target_node_id"]),
        ("ix_video_scene_executions_status", ["status"]),
        ("ix_video_scene_executions_lease_owner", ["lease_owner"]),
        ("ix_video_scene_executions_lease_expires_at", ["lease_expires_at"]),
        ("ix_video_scene_executions_available_at", ["available_at"]),
        ("ix_video_scene_executions_provider_request_id", ["provider_request_id"]),
        ("ix_video_scene_executions_provider_state", ["provider_state"]),
        ("ix_video_scene_executions_provider_state_lookup", ["provider", "provider_state"]),
        ("ix_video_scene_executions_output_checksum", ["output_checksum"]),
        ("ix_video_scene_executions_claim", ["status", "available_at", "created_at"]),
        ("ix_video_scene_executions_execution_status_scene", ["video_execution_id", "status", "scene_index"]),
    ):
        if name not in scene_indexes:
            op.create_index(name, "video_scene_executions", fields)


def downgrade() -> None:
    op.drop_table("video_scene_executions")
    op.drop_table("video_executions")
