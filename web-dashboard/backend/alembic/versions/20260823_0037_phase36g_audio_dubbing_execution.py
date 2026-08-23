"""Add Phase 36G durable stock-voice dubbing execution authority.

Revision ID: 20260823_0037
Revises: 20260822_0036
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260823_0037"
down_revision = "20260822_0036"
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
        "audio_speech_executions",
        "audio_transcript_executions",
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "Phase 36G dubbing migration requires tables: " + ", ".join(missing)
        )

    if "audio_dubbing_executions" not in tables:
        op.create_table(
            "audio_dubbing_executions",
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
                "requested_by_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "status", sa.String(40), nullable=False, server_default="planned"
            ),
            sa.Column(
                "provider_state",
                sa.String(40),
                nullable=False,
                server_default="not_started",
            ),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(160), nullable=False),
            sa.Column(
                "source_transcript_storage_backend", sa.String(32), nullable=False
            ),
            sa.Column("source_transcript_storage_key", sa.Text(), nullable=False),
            sa.Column(
                "source_transcript_object_checksum", sa.String(64), nullable=False
            ),
            sa.Column(
                "source_transcript_object_size_bytes", sa.BigInteger(), nullable=False
            ),
            sa.Column("source_transcript_checksum", sa.String(64), nullable=False),
            sa.Column("source_language", sa.String(32), nullable=False),
            sa.Column("target_language", sa.String(32), nullable=False),
            sa.Column("segment_count", sa.Integer(), nullable=False),
            sa.Column("speaker_count", sa.Integer(), nullable=False),
            sa.Column(
                "voice_bindings",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            ),
            sa.Column("output_profile_id", sa.String(80), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("lease_owner", sa.String(160)),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column(
                "fencing_token", sa.Integer(), nullable=False, server_default="0"
            ),
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
            sa.Column(
                "estimated_translation_cost_usd",
                sa.Float(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "max_translation_cost_usd",
                sa.Float(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("actual_translation_cost_usd", sa.Float()),
            sa.Column(
                "speech_cost_upper_bound_usd",
                sa.Float(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "max_total_cost_usd", sa.Float(), nullable=False, server_default="0"
            ),
            sa.Column("actual_total_cost_usd", sa.Float()),
            sa.Column(
                "cost_basis", sa.String(80), nullable=False, server_default="unknown"
            ),
            sa.Column("translation_storage_backend", sa.String(32)),
            sa.Column("translation_storage_key", sa.Text()),
            sa.Column("translation_checksum", sa.String(64)),
            sa.Column("translation_size_bytes", sa.BigInteger()),
            sa.Column("translation_text_sha256", sa.String(64)),
            sa.Column(
                "speech_pipelines",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column(
                "replacement_history",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column(
                "final_graph_id",
                sa.String(36),
                sa.ForeignKey("media_asset_graphs.id", ondelete="SET NULL"),
            ),
            sa.Column("final_output_storage_backend", sa.String(32)),
            sa.Column("final_output_storage_key", sa.Text()),
            sa.Column("final_output_checksum", sa.String(64)),
            sa.Column("final_output_size_bytes", sa.BigInteger()),
            sa.Column("final_output_duration_seconds", sa.Float()),
            sa.Column("error_code", sa.String(120)),
            sa.Column("error_message", sa.Text()),
            sa.Column("armed_at", sa.DateTime(timezone=True)),
            sa.Column("provider_submitted_at", sa.DateTime(timezone=True)),
            sa.Column("translation_completed_at", sa.DateTime(timezone=True)),
            sa.Column("speech_armed_at", sa.DateTime(timezone=True)),
            sa.Column("render_started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_audio_dubbing_execution_org_idempotency",
            ),
        )
    else:
        required_columns = {
            "id",
            "organization_id",
            "requested_by_id",
            "status",
            "provider_state",
            "idempotency_key",
            "provider",
            "model",
            "source_transcript_storage_backend",
            "source_transcript_storage_key",
            "source_transcript_object_checksum",
            "source_transcript_object_size_bytes",
            "source_transcript_checksum",
            "source_language",
            "target_language",
            "segment_count",
            "speaker_count",
            "voice_bindings",
            "output_profile_id",
            "attempts",
            "max_attempts",
            "lease_token",
            "lease_owner",
            "lease_expires_at",
            "fencing_token",
            "provider_request_id",
            "estimated_translation_cost_usd",
            "max_translation_cost_usd",
            "speech_cost_upper_bound_usd",
            "max_total_cost_usd",
            "translation_storage_key",
            "translation_checksum",
            "speech_pipelines",
            "replacement_history",
            "final_graph_id",
            "final_output_checksum",
            "armed_at",
            "provider_submitted_at",
            "translation_completed_at",
            "speech_armed_at",
            "render_started_at",
            "completed_at",
            "created_at",
            "updated_at",
        }
        existing = {
            item["name"] for item in inspector.get_columns("audio_dubbing_executions")
        }
        missing_columns = sorted(required_columns - existing)
        if missing_columns:
            raise RuntimeError(
                "Existing audio_dubbing_executions is incomplete: "
                + ", ".join(missing_columns)
            )

    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("audio_dubbing_executions")
    }
    for name, fields in (
        ("ix_audio_dubbing_executions_organization_id", ["organization_id"]),
        ("ix_audio_dubbing_executions_workspace_id", ["workspace_id"]),
        ("ix_audio_dubbing_executions_project_id", ["project_id"]),
        ("ix_audio_dubbing_executions_studio_job_id", ["studio_job_id"]),
        ("ix_audio_dubbing_executions_studio_asset_id", ["studio_asset_id"]),
        ("ix_audio_dubbing_executions_requested_by_id", ["requested_by_id"]),
        ("ix_audio_dubbing_executions_status", ["status"]),
        ("ix_audio_dubbing_executions_provider_state", ["provider_state"]),
        (
            "ix_audio_dubbing_executions_source_transcript_checksum",
            ["source_transcript_checksum"],
        ),
        ("ix_audio_dubbing_executions_lease_owner", ["lease_owner"]),
        ("ix_audio_dubbing_executions_lease_expires_at", ["lease_expires_at"]),
        ("ix_audio_dubbing_executions_available_at", ["available_at"]),
        ("ix_audio_dubbing_executions_provider_request_id", ["provider_request_id"]),
        ("ix_audio_dubbing_executions_translation_checksum", ["translation_checksum"]),
        ("ix_audio_dubbing_executions_final_graph_id", ["final_graph_id"]),
        (
            "ix_audio_dubbing_executions_final_output_checksum",
            ["final_output_checksum"],
        ),
        (
            "ix_audio_dubbing_executions_org_status_created",
            ["organization_id", "status", "created_at"],
        ),
        ("ix_audio_dubbing_executions_claim", ["status", "available_at", "created_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "audio_dubbing_executions", fields)


def downgrade() -> None:
    bind = op.get_bind()
    if "audio_dubbing_executions" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("audio_dubbing_executions")
