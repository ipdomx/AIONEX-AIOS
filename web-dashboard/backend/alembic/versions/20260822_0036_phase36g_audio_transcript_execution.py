"""Add Phase 36G durable governed audio transcription authority.

Revision ID: 20260822_0036
Revises: 20260822_0035
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260822_0036"
down_revision = "20260822_0035"
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
        "media_asset_graphs",
        "media_asset_nodes",
        "studio_jobs",
        "studio_assets",
        "audio_speech_executions",
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "Phase 36G transcript migration requires tables: " + ", ".join(missing)
        )

    if "audio_transcript_executions" not in tables:
        op.create_table(
            "audio_transcript_executions",
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
            sa.Column(
                "operation",
                sa.String(40),
                nullable=False,
                server_default="transcribe",
            ),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(160), nullable=False),
            sa.Column(
                "status", sa.String(32), nullable=False, server_default="planned"
            ),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("source_storage_backend", sa.String(32), nullable=False),
            sa.Column("source_storage_key", sa.Text(), nullable=False),
            sa.Column("source_checksum", sa.String(64), nullable=False),
            sa.Column("source_size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("source_media_type", sa.String(120), nullable=False),
            sa.Column("source_duration_ms", sa.Integer(), nullable=False),
            sa.Column("source_sample_rate_hz", sa.Integer(), nullable=False),
            sa.Column("source_channels", sa.Integer(), nullable=False),
            sa.Column("language", sa.String(32), nullable=False),
            sa.Column(
                "response_format", sa.String(24), nullable=False, server_default="json"
            ),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("lease_owner", sa.String(160)),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column(
                "fencing_token", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("available_at", sa.DateTime(timezone=True)),
            sa.Column(
                "provider_state",
                sa.String(40),
                nullable=False,
                server_default="not_started",
            ),
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
            sa.Column(
                "estimated_cost_usd", sa.Float(), nullable=False, server_default="0"
            ),
            sa.Column("max_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("actual_cost_usd", sa.Float()),
            sa.Column(
                "cost_basis",
                sa.String(64),
                nullable=False,
                server_default="unknown",
            ),
            sa.Column("output_storage_backend", sa.String(32)),
            sa.Column("output_storage_key", sa.Text()),
            sa.Column("output_checksum", sa.String(64)),
            sa.Column("output_size_bytes", sa.BigInteger()),
            sa.Column("transcript_checksum", sa.String(64)),
            sa.Column("transcript_text_sha256", sa.String(64)),
            sa.Column("transcript_characters", sa.Integer()),
            sa.Column("segment_count", sa.Integer()),
            sa.Column("speaker_count", sa.Integer()),
            sa.Column("transcript_language", sa.String(32)),
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
                name="uq_audio_transcript_execution_org_idempotency",
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
            "status",
            "idempotency_key",
            "source_storage_backend",
            "source_storage_key",
            "source_checksum",
            "source_size_bytes",
            "source_media_type",
            "source_duration_ms",
            "source_sample_rate_hz",
            "source_channels",
            "language",
            "response_format",
            "attempts",
            "max_attempts",
            "lease_token",
            "lease_owner",
            "lease_expires_at",
            "fencing_token",
            "available_at",
            "provider_state",
            "provider_request_id",
            "provider_response_metadata",
            "usage_metadata",
            "estimated_cost_usd",
            "max_cost_usd",
            "actual_cost_usd",
            "cost_basis",
            "output_storage_backend",
            "output_storage_key",
            "output_checksum",
            "output_size_bytes",
            "transcript_checksum",
            "transcript_text_sha256",
            "transcript_characters",
            "segment_count",
            "speaker_count",
            "transcript_language",
            "error_code",
            "error_message",
            "armed_at",
            "provider_submitted_at",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        }
        existing = {
            item["name"]
            for item in inspector.get_columns("audio_transcript_executions")
        }
        missing_columns = sorted(required_columns - existing)
        if missing_columns:
            raise RuntimeError(
                "Existing audio_transcript_executions is incomplete: "
                + ", ".join(missing_columns)
            )

    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("audio_transcript_executions")
    }
    for name, fields in (
        ("ix_audio_transcript_executions_organization_id", ["organization_id"]),
        ("ix_audio_transcript_executions_workspace_id", ["workspace_id"]),
        ("ix_audio_transcript_executions_project_id", ["project_id"]),
        ("ix_audio_transcript_executions_studio_job_id", ["studio_job_id"]),
        ("ix_audio_transcript_executions_studio_asset_id", ["studio_asset_id"]),
        ("ix_audio_transcript_executions_graph_id", ["graph_id"]),
        ("ix_audio_transcript_executions_target_node_id", ["target_node_id"]),
        ("ix_audio_transcript_executions_requested_by_id", ["requested_by_id"]),
        ("ix_audio_transcript_executions_operation", ["operation"]),
        ("ix_audio_transcript_executions_provider", ["provider"]),
        ("ix_audio_transcript_executions_status", ["status"]),
        ("ix_audio_transcript_executions_source_checksum", ["source_checksum"]),
        ("ix_audio_transcript_executions_lease_owner", ["lease_owner"]),
        ("ix_audio_transcript_executions_lease_expires_at", ["lease_expires_at"]),
        ("ix_audio_transcript_executions_available_at", ["available_at"]),
        ("ix_audio_transcript_executions_provider_state", ["provider_state"]),
        ("ix_audio_transcript_executions_provider_request_id", ["provider_request_id"]),
        ("ix_audio_transcript_executions_output_checksum", ["output_checksum"]),
        ("ix_audio_transcript_executions_transcript_checksum", ["transcript_checksum"]),
        (
            "ix_audio_transcript_executions_transcript_text_sha256",
            ["transcript_text_sha256"],
        ),
        (
            "ix_audio_transcript_executions_org_status_created",
            ["organization_id", "status", "created_at"],
        ),
        (
            "ix_audio_transcript_executions_claim",
            ["status", "available_at", "created_at"],
        ),
        (
            "ix_audio_transcript_executions_graph_status",
            ["graph_id", "status"],
        ),
    ):
        if name not in indexes:
            op.create_index(name, "audio_transcript_executions", fields)


def downgrade() -> None:
    bind = op.get_bind()
    if "audio_transcript_executions" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("audio_transcript_executions")
