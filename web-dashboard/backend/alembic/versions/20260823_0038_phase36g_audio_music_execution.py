"""Add Phase 36G durable low-cost Lyria music execution authority.

Revision ID: 20260823_0038
Revises: 20260823_0037
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260823_0038"
down_revision = "20260823_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required = {
        "organizations",
        "users",
        "workspaces",
        "projects",
        "studio_jobs",
        "studio_assets",
        "media_asset_graphs",
        "media_asset_nodes",
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "Phase 36G music migration requires tables: " + ", ".join(missing)
        )

    if "audio_music_executions" not in tables:
        op.create_table(
            "audio_music_executions",
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
                sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
            ),
            sa.Column(
                "studio_job_id",
                sa.String(36),
                sa.ForeignKey("studio_jobs.id", ondelete="SET NULL"),
            ),
            sa.Column(
                "studio_asset_id",
                sa.String(36),
                sa.ForeignKey("studio_assets.id", ondelete="SET NULL"),
            ),
            sa.Column(
                "graph_id",
                sa.String(36),
                sa.ForeignKey("media_asset_graphs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "target_node_id",
                sa.String(36),
                sa.ForeignKey("media_asset_nodes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "requested_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("operation", sa.String(40), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(160), nullable=False),
            sa.Column("tier", sa.String(24), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column(
                "provider_state",
                sa.String(40),
                nullable=False,
                server_default="not_started",
            ),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("plan_checksum", sa.String(64), nullable=False),
            sa.Column("runtime_evidence_sha256", sa.String(64), nullable=False),
            sa.Column("pricing_evidence_sha256", sa.String(64), nullable=False),
            sa.Column("prompt_sha256", sa.String(64), nullable=False),
            sa.Column("prompt_characters", sa.Integer(), nullable=False),
            sa.Column("lyrics_sha256", sa.String(64)),
            sa.Column(
                "lyrics_characters", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "instrumental_only", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("rights_basis", sa.String(40), nullable=False),
            sa.Column("rights_evidence_sha256", sa.String(64)),
            sa.Column(
                "final_generation_approved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("final_approval_evidence_sha256", sa.String(64)),
            sa.Column("prior_draft_checksum", sa.String(64)),
            sa.Column(
                "preview_model", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "synthid_disclosure_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "request_options",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column("output_format", sa.String(16), nullable=False, server_default="mp3"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("lease_owner", sa.String(160)),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("available_at", sa.DateTime(timezone=True)),
            sa.Column("provider_request_id", sa.String(200)),
            sa.Column(
                "provider_response_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column(
                "usage_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
            sa.Column("max_cost_usd", sa.Float(), nullable=False),
            sa.Column("actual_cost_usd", sa.Float()),
            sa.Column(
                "cost_basis", sa.String(64), nullable=False, server_default="unknown"
            ),
            sa.Column("output_storage_backend", sa.String(32)),
            sa.Column("output_storage_key", sa.Text()),
            sa.Column("output_checksum", sa.String(64)),
            sa.Column("output_size_bytes", sa.BigInteger()),
            sa.Column("output_duration_seconds", sa.Float()),
            sa.Column("returned_text_sha256", sa.String(64)),
            sa.Column(
                "returned_text_characters",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("error_code", sa.String(120)),
            sa.Column("error_message", sa.Text()),
            sa.Column("armed_at", sa.DateTime(timezone=True)),
            sa.Column("provider_submitted_at", sa.DateTime(timezone=True)),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_audio_music_execution_org_idempotency",
            ),
        )
    else:
        required_columns = {
            "id",
            "organization_id",
            "graph_id",
            "target_node_id",
            "requested_by_id",
            "operation",
            "provider",
            "model",
            "tier",
            "status",
            "provider_state",
            "idempotency_key",
            "plan_checksum",
            "runtime_evidence_sha256",
            "pricing_evidence_sha256",
            "prompt_sha256",
            "prompt_characters",
            "instrumental_only",
            "rights_basis",
            "final_approval_evidence_sha256",
            "preview_model",
            "synthid_disclosure_required",
            "max_attempts",
            "fencing_token",
            "estimated_cost_usd",
            "max_cost_usd",
            "created_at",
            "updated_at",
        }
        existing = {
            item["name"] for item in inspector.get_columns("audio_music_executions")
        }
        missing_columns = sorted(required_columns - existing)
        if missing_columns:
            raise RuntimeError(
                "Existing audio_music_executions is incomplete: "
                + ", ".join(missing_columns)
            )

    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("audio_music_executions")
    }
    definitions = (
        ("ix_audio_music_executions_organization_id", ["organization_id"]),
        ("ix_audio_music_executions_workspace_id", ["workspace_id"]),
        ("ix_audio_music_executions_project_id", ["project_id"]),
        ("ix_audio_music_executions_studio_job_id", ["studio_job_id"]),
        ("ix_audio_music_executions_studio_asset_id", ["studio_asset_id"]),
        ("ix_audio_music_executions_graph_id", ["graph_id"]),
        ("ix_audio_music_executions_target_node_id", ["target_node_id"]),
        ("ix_audio_music_executions_requested_by_id", ["requested_by_id"]),
        ("ix_audio_music_executions_operation", ["operation"]),
        ("ix_audio_music_executions_provider", ["provider"]),
        ("ix_audio_music_executions_tier", ["tier"]),
        ("ix_audio_music_executions_status", ["status"]),
        ("ix_audio_music_executions_provider_state", ["provider_state"]),
        ("ix_audio_music_executions_plan_checksum", ["plan_checksum"]),
        ("ix_audio_music_executions_runtime_evidence_sha256", ["runtime_evidence_sha256"]),
        ("ix_audio_music_executions_pricing_evidence_sha256", ["pricing_evidence_sha256"]),
        ("ix_audio_music_executions_prompt_sha256", ["prompt_sha256"]),
        ("ix_audio_music_executions_lyrics_sha256", ["lyrics_sha256"]),
        ("ix_audio_music_executions_rights_evidence_sha256", ["rights_evidence_sha256"]),
        ("ix_audio_music_executions_final_approval_evidence_sha256", ["final_approval_evidence_sha256"]),
        ("ix_audio_music_executions_prior_draft_checksum", ["prior_draft_checksum"]),
        ("ix_audio_music_executions_lease_owner", ["lease_owner"]),
        ("ix_audio_music_executions_lease_expires_at", ["lease_expires_at"]),
        ("ix_audio_music_executions_available_at", ["available_at"]),
        ("ix_audio_music_executions_provider_request_id", ["provider_request_id"]),
        ("ix_audio_music_executions_output_checksum", ["output_checksum"]),
        ("ix_audio_music_executions_returned_text_sha256", ["returned_text_sha256"]),
        (
            "ix_audio_music_executions_org_status_created",
            ["organization_id", "status", "created_at"],
        ),
        (
            "ix_audio_music_executions_claim",
            ["status", "available_at", "created_at"],
        ),
        (
            "ix_audio_music_executions_graph_status",
            ["graph_id", "status"],
        ),
        (
            "ix_audio_music_executions_provider_state_lookup",
            ["provider", "provider_state"],
        ),
    )
    for name, fields in definitions:
        if name not in indexes:
            op.create_index(name, "audio_music_executions", fields)


def downgrade() -> None:
    bind = op.get_bind()
    if "audio_music_executions" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("audio_music_executions")
