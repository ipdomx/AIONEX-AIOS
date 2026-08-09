"""Phase 34D durable 3D generation jobs and protected artifact metadata.

Revision ID: 20260809_0013
Revises: 20260809_0012
"""
from alembic import op
import sqlalchemy as sa

revision = "20260809_0013"
down_revision = "20260809_0012"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "three_d_generation_jobs" not in tables:
        op.create_table(
            "three_d_generation_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False, server_default="runpod"),
            sa.Column("provider_job_id", sa.String(160)),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("stage", sa.String(64), nullable=False, server_default="queued"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("input_object_key", sa.Text(), nullable=False),
            sa.Column("input_content_type", sa.String(120), nullable=False),
            sa.Column("input_size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("input_sha256", sa.String(64), nullable=False),
            sa.Column("request_options", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("provider_delay_ms", sa.BigInteger()),
            sa.Column("provider_execution_ms", sa.BigInteger()),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("metering_status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("error_code", sa.String(120)),
            sa.Column("error_message", sa.Text()),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
            sa.Column("cancelled_at", sa.DateTime(timezone=True)),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("provider", "provider_job_id", name="uq_three_d_jobs_provider_job"),
        )
    for name, columns in (
        ("ix_three_d_jobs_org_status_created", ["organization_id", "status", "created_at"]),
        ("ix_three_d_jobs_project_created", ["project_id", "created_at"]),
        ("ix_three_d_jobs_user_created", ["requested_by_id", "created_at"]),
        ("ix_three_d_generation_jobs_organization_id", ["organization_id"]),
        ("ix_three_d_generation_jobs_workspace_id", ["workspace_id"]),
        ("ix_three_d_generation_jobs_project_id", ["project_id"]),
        ("ix_three_d_generation_jobs_requested_by_id", ["requested_by_id"]),
        ("ix_three_d_generation_jobs_provider_job_id", ["provider_job_id"]),
        ("ix_three_d_generation_jobs_status", ["status"]),
    ):
        if name not in _indexes("three_d_generation_jobs"):
            op.create_index(name, "three_d_generation_jobs", columns)

    if "three_d_artifacts" not in _tables():
        op.create_table(
            "three_d_artifacts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("job_id", sa.String(36), sa.ForeignKey("three_d_generation_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("filename", sa.String(300), nullable=False),
            sa.Column("media_type", sa.String(120), nullable=False, server_default="model/gltf-binary"),
            sa.Column("object_key", sa.Text(), nullable=False),
            sa.Column("checksum", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
            sa.Column("artifact_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("job_id", name="uq_three_d_artifacts_job"),
        )
    for name, columns in (
        ("ix_three_d_artifacts_project_created", ["project_id", "created_at"]),
        ("ix_three_d_artifacts_org_status", ["organization_id", "status"]),
        ("ix_three_d_artifacts_organization_id", ["organization_id"]),
        ("ix_three_d_artifacts_project_id", ["project_id"]),
        ("ix_three_d_artifacts_job_id", ["job_id"]),
        ("ix_three_d_artifacts_created_by_id", ["created_by_id"]),
        ("ix_three_d_artifacts_checksum", ["checksum"]),
        ("ix_three_d_artifacts_status", ["status"]),
        ("ix_three_d_artifacts_expires_at", ["expires_at"]),
    ):
        if name not in _indexes("three_d_artifacts"):
            op.create_index(name, "three_d_artifacts", columns)


def downgrade() -> None:
    if "three_d_artifacts" in _tables():
        op.drop_table("three_d_artifacts")
    if "three_d_generation_jobs" in _tables():
        op.drop_table("three_d_generation_jobs")
