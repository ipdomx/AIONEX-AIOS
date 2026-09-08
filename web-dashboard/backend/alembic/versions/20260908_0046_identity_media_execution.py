"""phase36 identity media execution

Revision ID: 20260908_0046
Revises: 20260907_0045
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260908_0046"
down_revision = "20260907_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_media_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("identity_basis", sa.String(length=40), nullable=False),
        sa.Column("provider_access", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="replicate"),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("provider_state", sa.String(length=40), nullable=False, server_default="not_started"),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("subject_reference", sa.String(length=200), nullable=False),
        sa.Column("named_real_person_reference", sa.String(length=200), nullable=True),
        sa.Column("rights_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("license_reference", sa.String(length=500), nullable=True),
        sa.Column("synthetic_media_disclosure_accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("commercial_use_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("commercial_use_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claims_real_identity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("input_storage_keys", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("input_checksums", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("provider_job_id", sa.String(length=200), nullable=True),
        sa.Column("secondary_provider_job_id", sa.String(length=200), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("polls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_polls", sa.Integer(), nullable=False, server_default="240"),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_cost_usd", sa.Float(), nullable=True),
        sa.Column("cost_basis", sa.String(length=64), nullable=False, server_default="user_authorized_ceiling_provider_price_unverified"),
        sa.Column("output_storage_backend", sa.String(length=32), nullable=True),
        sa.Column("output_storage_key", sa.Text(), nullable=True),
        sa.Column("output_checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("output_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("output_media_type", sa.String(length=120), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("armed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_identity_media_execution_org_idempotency"),
    )
    op.create_index("ix_identity_media_executions_org_status_created", "identity_media_executions", ["organization_id", "status", "created_at"])
    op.create_index("ix_identity_media_executions_claim", "identity_media_executions", ["status", "available_at", "created_at"])
    op.create_index("ix_identity_media_executions_provider_state", "identity_media_executions", ["provider", "provider_state"])
    op.create_index("ix_identity_media_executions_user_created", "identity_media_executions", ["requested_by_id", "created_at"])
    for column in ("organization_id", "project_id", "requested_by_id", "operation", "identity_basis", "provider", "status", "provider_state", "rights_evidence_sha256", "provider_job_id", "secondary_provider_job_id", "lease_owner", "lease_expires_at", "available_at", "output_checksum_sha256"):
        op.create_index(f"ix_identity_media_executions_{column}", "identity_media_executions", [column])


def downgrade() -> None:
    op.drop_table("identity_media_executions")
