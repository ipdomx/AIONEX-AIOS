"""Add Phase 36D creative media DAG and render-step persistence.

Revision ID: 20260817_0030
Revises: 20260817_0029
"""
from alembic import op
import sqlalchemy as sa

revision = "20260817_0030"
down_revision = "20260817_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    required = {"organizations", "users", "studio_jobs", "studio_assets"}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "Phase 36D media migration requires tables: " + ", ".join(missing)
        )
    if "media_asset_graphs" not in tables:
        op.create_table(
            "media_asset_graphs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="SET NULL")),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
            sa.Column("studio_job_id", sa.String(36), sa.ForeignKey("studio_jobs.id", ondelete="SET NULL")),
            sa.Column("studio_asset_id", sa.String(36), sa.ForeignKey("studio_assets.id", ondelete="SET NULL")),
            sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("asset_kind", sa.String(40), nullable=False),
            sa.Column("output_profile", sa.String(80), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("graph_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("graph_checksum", sa.String(64), nullable=False),
            sa.Column("graph_metadata", sa.JSON(), nullable=False),
            sa.Column("rights_metadata", sa.JSON(), nullable=False),
            sa.Column("provenance", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_media_graph_org_idempotency"),
        )
        for name, fields in (
            ("ix_media_asset_graphs_organization_id", ["organization_id"]),
            ("ix_media_asset_graphs_workspace_id", ["workspace_id"]),
            ("ix_media_asset_graphs_project_id", ["project_id"]),
            ("ix_media_asset_graphs_studio_job_id", ["studio_job_id"]),
            ("ix_media_asset_graphs_studio_asset_id", ["studio_asset_id"]),
            ("ix_media_asset_graphs_created_by_id", ["created_by_id"]),
            ("ix_media_asset_graphs_asset_kind", ["asset_kind"]),
            ("ix_media_asset_graphs_status", ["status"]),
            ("ix_media_asset_graphs_graph_checksum", ["graph_checksum"]),
            ("ix_media_graphs_org_status_created", ["organization_id", "status", "created_at"]),
            ("ix_media_graphs_project_created", ["project_id", "created_at"]),
        ):
            op.create_index(name, "media_asset_graphs", fields)

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "media_asset_nodes" not in tables:
        op.create_table(
            "media_asset_nodes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("graph_id", sa.String(36), sa.ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("logical_key", sa.String(160), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("node_type", sa.String(40), nullable=False),
            sa.Column("media_type", sa.String(120)),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("storage_backend", sa.String(32)),
            sa.Column("storage_key", sa.Text()),
            sa.Column("checksum", sa.String(64)),
            sa.Column("size_bytes", sa.BigInteger()),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("source_metadata", sa.JSON(), nullable=False),
            sa.Column("prompt_metadata", sa.JSON(), nullable=False),
            sa.Column("rights_metadata", sa.JSON(), nullable=False),
            sa.Column("provenance", sa.JSON(), nullable=False),
            sa.Column("scene_metadata", sa.JSON(), nullable=False),
            sa.Column("timeline_metadata", sa.JSON(), nullable=False),
            sa.Column("operation_metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("graph_id", "logical_key", "revision", name="uq_media_node_graph_key_revision"),
            sa.UniqueConstraint("graph_id", "idempotency_key", name="uq_media_node_graph_idempotency"),
        )
        for name, fields in (
            ("ix_media_asset_nodes_graph_id", ["graph_id"]),
            ("ix_media_asset_nodes_organization_id", ["organization_id"]),
            ("ix_media_asset_nodes_created_by_id", ["created_by_id"]),
            ("ix_media_asset_nodes_node_type", ["node_type"]),
            ("ix_media_asset_nodes_status", ["status"]),
            ("ix_media_asset_nodes_checksum", ["checksum"]),
            ("ix_media_nodes_graph_status", ["graph_id", "status"]),
            ("ix_media_nodes_org_status", ["organization_id", "status"]),
        ):
            op.create_index(name, "media_asset_nodes", fields)

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "media_asset_edges" not in tables:
        op.create_table(
            "media_asset_edges",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("graph_id", sa.String(36), sa.ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_node_id", sa.String(36), sa.ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("child_node_id", sa.String(36), sa.ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("dependency_type", sa.String(40), nullable=False, server_default="input"),
            sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("graph_id", "parent_node_id", "child_node_id", "dependency_type", name="uq_media_edge_dependency"),
        )
        for name, fields in (
            ("ix_media_asset_edges_graph_id", ["graph_id"]),
            ("ix_media_asset_edges_organization_id", ["organization_id"]),
            ("ix_media_asset_edges_parent_node_id", ["parent_node_id"]),
            ("ix_media_asset_edges_child_node_id", ["child_node_id"]),
            ("ix_media_edges_graph_ordinal", ["graph_id", "ordinal"]),
        ):
            op.create_index(name, "media_asset_edges", fields)

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "media_render_steps" not in tables:
        op.create_table(
            "media_render_steps",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("graph_id", sa.String(36), sa.ForeignKey("media_asset_graphs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_node_id", sa.String(36), sa.ForeignKey("media_asset_nodes.id", ondelete="CASCADE"), nullable=False),
            sa.Column("step_key", sa.String(160), nullable=False),
            sa.Column("operation", sa.String(60), nullable=False),
            sa.Column("output_profile", sa.String(80), nullable=False),
            sa.Column("engine", sa.String(60), nullable=False, server_default="ffmpeg"),
            sa.Column("engine_version", sa.String(40), nullable=False),
            sa.Column("hardware_adapter", sa.String(40), nullable=False, server_default="software"),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("input_checksums", sa.JSON(), nullable=False),
            sa.Column("output_checksum", sa.String(64)),
            sa.Column("command_hash", sa.String(64)),
            sa.Column("result_metadata", sa.JSON(), nullable=False),
            sa.Column("error_code", sa.String(120)),
            sa.Column("error_message", sa.Text()),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("graph_id", "step_key", name="uq_media_render_step_graph_key"),
            sa.UniqueConstraint("graph_id", "idempotency_key", name="uq_media_render_step_graph_idempotency"),
        )
        for name, fields in (
            ("ix_media_render_steps_graph_id", ["graph_id"]),
            ("ix_media_render_steps_organization_id", ["organization_id"]),
            ("ix_media_render_steps_target_node_id", ["target_node_id"]),
            ("ix_media_render_steps_operation", ["operation"]),
            ("ix_media_render_steps_status", ["status"]),
            ("ix_media_render_steps_output_checksum", ["output_checksum"]),
            ("ix_media_render_steps_org_status_created", ["organization_id", "status", "created_at"]),
            ("ix_media_render_steps_graph_status", ["graph_id", "status"]),
        ):
            op.create_index(name, "media_render_steps", fields)


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("media_render_steps", "media_asset_edges", "media_asset_nodes", "media_asset_graphs"):
        if table in tables:
            op.drop_table(table)
            tables.remove(table)
