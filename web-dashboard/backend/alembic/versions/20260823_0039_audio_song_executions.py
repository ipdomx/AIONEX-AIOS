"""Add durable open-song execution authority.

Revision ID: 20260823_0039
Revises: 20260823_0038
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0039"
down_revision: str | None = "20260823_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required_dependencies = {
        "organizations",
        "users",
        "workspaces",
        "projects",
        "studio_jobs",
        "studio_assets",
        "media_asset_graphs",
        "media_asset_nodes",
    }
    missing_dependencies = sorted(required_dependencies - tables)
    if missing_dependencies:
        raise RuntimeError(
            "Open-song migration requires tables: "
            + ", ".join(missing_dependencies)
        )

    if "audio_song_executions" not in tables:
        op.create_table(
            "audio_song_executions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=True),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("studio_job_id", sa.String(length=36), nullable=True),
            sa.Column("studio_asset_id", sa.String(length=36), nullable=True),
            sa.Column("graph_id", sa.String(length=36), nullable=False),
            sa.Column("target_node_id", sa.String(length=36), nullable=False),
            sa.Column("requested_by_id", sa.String(length=36), nullable=False),
            sa.Column(
                "operation",
                sa.String(length=40),
                nullable=False,
                server_default="generate-open-song",
            ),
            sa.Column("route_id", sa.String(length=80), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("model", sa.String(length=160), nullable=False),
            sa.Column("model_revision", sa.String(length=64), nullable=False),
            sa.Column("language_model", sa.String(length=160), nullable=False),
            sa.Column("language_model_revision", sa.String(length=64), nullable=False),
            sa.Column("source_commit", sa.String(length=64), nullable=False),
            sa.Column("base_container_image_repository", sa.String(length=240), nullable=True),
            sa.Column("base_container_image_index_digest", sa.String(length=71), nullable=True),
            sa.Column("base_container_image_digest", sa.String(length=71), nullable=True),
            sa.Column("endpoint_id_sha256", sa.String(length=64), nullable=True),
            sa.Column("image_sbom_sha256", sa.String(length=64), nullable=True),
            sa.Column("handler_source_sha256", sa.String(length=64), nullable=True),
            sa.Column("container_image_repository", sa.String(length=240), nullable=True),
            sa.Column("container_image_index_digest", sa.String(length=71), nullable=True),
            sa.Column("container_image_digest", sa.String(length=71), nullable=True),
            sa.Column("separation_model", sa.String(length=80), nullable=False),
            sa.Column("separation_revision", sa.String(length=64), nullable=False),
            sa.Column("separation_source_commit", sa.String(length=64), nullable=False),
            sa.Column("separation_checkpoint_sha256", sa.String(length=64), nullable=False),
            sa.Column(
                "status", sa.String(length=32), nullable=False, server_default="planned"
            ),
            sa.Column(
                "provider_state",
                sa.String(length=40),
                nullable=False,
                server_default="not_started",
            ),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column("plan_checksum", sa.String(length=64), nullable=False),
            sa.Column("runtime_evidence_sha256", sa.String(length=64), nullable=False),
            sa.Column("pricing_evidence_sha256", sa.String(length=64), nullable=False),
            sa.Column("license_evidence_sha256", sa.String(length=64), nullable=False),
            sa.Column("title_sha256", sa.String(length=64), nullable=False),
            sa.Column("title_characters", sa.Integer(), nullable=False),
            sa.Column("concept_sha256", sa.String(length=64), nullable=False),
            sa.Column("concept_characters", sa.Integer(), nullable=False),
            sa.Column("lyrics_sha256", sa.String(length=64), nullable=False),
            sa.Column("lyrics_characters", sa.Integer(), nullable=False),
            sa.Column("language", sa.String(length=24), nullable=False),
            sa.Column("duration_seconds", sa.Integer(), nullable=False),
            sa.Column("bpm", sa.Integer(), nullable=False),
            sa.Column("musical_key", sa.String(length=16), nullable=False),
            sa.Column("time_signature", sa.Integer(), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=False),
            sa.Column("output_profile_id", sa.String(length=80), nullable=False),
            sa.Column("rights_basis", sa.String(length=32), nullable=False),
            sa.Column("rights_evidence_sha256", sa.String(length=64), nullable=True),
            sa.Column(
                "commercial_use_authorized",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "provider_terms_accepted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "ai_generated_disclosure_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "estimated_cost_usd", sa.Float(), nullable=False, server_default="0"
            ),
            sa.Column("max_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("actual_cost_usd", sa.Float(), nullable=True),
            sa.Column("cost_basis", sa.String(length=80), nullable=False),
            sa.Column(
                "rate_usd_per_second", sa.Float(), nullable=False, server_default="0"
            ),
            sa.Column(
                "max_billed_seconds", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("actual_billed_seconds", sa.Float(), nullable=True),
            sa.Column(
                "actual_cost_known",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("polls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lease_owner", sa.String(length=160), nullable=True),
            sa.Column("lease_token", sa.String(length=64), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_job_id", sa.String(length=240), nullable=True),
            sa.Column("provider_job_id_sha256", sa.String(length=64), nullable=True),
            sa.Column("provider_submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "provider_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            ),
            sa.Column("error_code", sa.String(length=120), nullable=True),
            sa.Column(
                "error_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            ),
            sa.Column("full_song_storage_key", sa.String(length=900), nullable=True),
            sa.Column("full_song_checksum", sa.String(length=64), nullable=True),
            sa.Column("full_song_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("full_song_duration_seconds", sa.Float(), nullable=True),
            sa.Column("full_song_media_type", sa.String(length=100), nullable=True),
            sa.Column(
                "stem_manifest", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            ),
            sa.Column("stem_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("final_output_storage_key", sa.String(length=900), nullable=True),
            sa.Column("final_output_checksum", sa.String(length=64), nullable=True),
            sa.Column("final_output_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("final_output_duration_seconds", sa.Float(), nullable=True),
            sa.Column(
                "final_audio_qa", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            ),
            sa.Column("studio_revision", sa.Integer(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["organization_id"], ["organizations.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id"], ["workspaces.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["project_id"], ["projects.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["studio_job_id"], ["studio_jobs.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["studio_asset_id"], ["studio_assets.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["graph_id"], ["media_asset_graphs.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["target_node_id"], ["media_asset_nodes.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["requested_by_id"], ["users.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_audio_song_execution_org_idempotency",
            ),
        )
    else:
        required_columns = {
            "id",
            "organization_id",
            "workspace_id",
            "project_id",
            "studio_job_id",
            "studio_asset_id",
            "graph_id",
            "target_node_id",
            "requested_by_id",
            "operation",
            "route_id",
            "provider",
            "model",
            "model_revision",
            "language_model",
            "language_model_revision",
            "source_commit",
            "base_container_image_repository",
            "base_container_image_index_digest",
            "base_container_image_digest",
            "endpoint_id_sha256",
            "image_sbom_sha256",
            "handler_source_sha256",
            "container_image_repository",
            "container_image_index_digest",
            "container_image_digest",
            "separation_model",
            "separation_revision",
            "separation_source_commit",
            "separation_checkpoint_sha256",
            "status",
            "provider_state",
            "idempotency_key",
            "plan_checksum",
            "runtime_evidence_sha256",
            "pricing_evidence_sha256",
            "license_evidence_sha256",
            "title_sha256",
            "title_characters",
            "concept_sha256",
            "concept_characters",
            "lyrics_sha256",
            "lyrics_characters",
            "language",
            "duration_seconds",
            "bpm",
            "musical_key",
            "time_signature",
            "seed",
            "output_profile_id",
            "rights_basis",
            "rights_evidence_sha256",
            "commercial_use_authorized",
            "provider_terms_accepted",
            "ai_generated_disclosure_required",
            "estimated_cost_usd",
            "max_cost_usd",
            "actual_cost_usd",
            "cost_basis",
            "rate_usd_per_second",
            "max_billed_seconds",
            "actual_billed_seconds",
            "actual_cost_known",
            "max_attempts",
            "attempts",
            "polls",
            "fencing_token",
            "lease_owner",
            "lease_token",
            "lease_expires_at",
            "available_at",
            "provider_job_id",
            "provider_job_id_sha256",
            "provider_submitted_at",
            "provider_completed_at",
            "provider_metadata",
            "error_code",
            "error_metadata",
            "full_song_storage_key",
            "full_song_checksum",
            "full_song_size_bytes",
            "full_song_duration_seconds",
            "full_song_media_type",
            "stem_manifest",
            "stem_count",
            "final_output_storage_key",
            "final_output_checksum",
            "final_output_size_bytes",
            "final_output_duration_seconds",
            "final_audio_qa",
            "studio_revision",
            "completed_at",
            "created_at",
            "updated_at",
        }
        existing_columns = {
            item["name"]
            for item in inspector.get_columns("audio_song_executions")
        }
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            raise RuntimeError(
                "Existing audio_song_executions is incomplete: "
                + ", ".join(missing_columns)
            )
        unique_constraints = {
            item.get("name")
            for item in inspector.get_unique_constraints("audio_song_executions")
        }
        if "uq_audio_song_execution_org_idempotency" not in unique_constraints:
            raise RuntimeError(
                "Existing audio_song_executions lacks its tenant idempotency constraint"
            )

    inspector = sa.inspect(bind)
    existing_indexes = {
        item["name"]
        for item in inspector.get_indexes("audio_song_executions")
    }
    definitions = [
        *(
            (
                f"ix_audio_song_executions_{column}",
                [column],
            )
            for column in (
                "organization_id",
                "workspace_id",
                "project_id",
                "studio_job_id",
                "studio_asset_id",
                "graph_id",
                "target_node_id",
                "requested_by_id",
                "status",
                "provider_state",
                "lease_expires_at",
                "available_at",
            )
        ),
        (
            "ix_audio_song_execution_claim",
            [
                "status",
                "provider_state",
                "available_at",
                "lease_expires_at",
                "created_at",
            ],
        ),
        (
            "ix_audio_song_execution_scope",
            ["organization_id", "requested_by_id", "created_at"],
        ),
    ]
    for name, columns in definitions:
        if name not in existing_indexes:
            op.create_index(
                name,
                "audio_song_executions",
                columns,
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "audio_song_executions" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("audio_song_executions")
