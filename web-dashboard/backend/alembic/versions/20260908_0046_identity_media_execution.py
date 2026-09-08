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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required_tables = {"organizations", "projects", "users"}
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        raise RuntimeError(
            "Identity Media migration requires tables: " + ", ".join(missing_tables)
        )

    if "identity_media_executions" not in tables:
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
            sa.UniqueConstraint(
                "organization_id",
                "idempotency_key",
                name="uq_identity_media_execution_org_idempotency",
            ),
        )
    else:
        required_columns = {
            "id", "organization_id", "project_id", "requested_by_id", "operation",
            "identity_basis", "provider_access", "provider", "model", "status",
            "provider_state", "idempotency_key", "subject_reference",
            "named_real_person_reference", "rights_evidence_sha256", "license_reference",
            "synthetic_media_disclosure_accepted", "commercial_use_requested",
            "commercial_use_authorized", "claims_real_identity", "request_payload",
            "input_storage_keys", "input_checksums", "provider_job_id",
            "secondary_provider_job_id", "provider_metadata", "attempts", "max_attempts",
            "polls", "max_polls", "lease_token", "lease_owner", "lease_expires_at",
            "fencing_token", "available_at", "estimated_cost_usd", "max_cost_usd",
            "actual_cost_usd", "cost_basis", "output_storage_backend", "output_storage_key",
            "output_checksum_sha256", "output_size_bytes", "output_media_type", "error_code",
            "error_message", "armed_at", "provider_submitted_at", "started_at",
            "completed_at", "cancelled_at", "version", "created_at", "updated_at",
        }
        existing_columns = {
            item["name"] for item in inspector.get_columns("identity_media_executions")
        }
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            raise RuntimeError(
                "Existing identity_media_executions table is incomplete: "
                + ", ".join(missing_columns)
            )

    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("identity_media_executions")
        if item.get("name")
    }
    definitions = (
        ("ix_identity_media_executions_organization_id", ["organization_id"]),
        ("ix_identity_media_executions_project_id", ["project_id"]),
        ("ix_identity_media_executions_requested_by_id", ["requested_by_id"]),
        ("ix_identity_media_executions_operation", ["operation"]),
        ("ix_identity_media_executions_identity_basis", ["identity_basis"]),
        ("ix_identity_media_executions_provider", ["provider"]),
        ("ix_identity_media_executions_status", ["status"]),
        ("ix_identity_media_executions_provider_state", ["provider_state"]),
        ("ix_identity_media_executions_rights_evidence_sha256", ["rights_evidence_sha256"]),
        ("ix_identity_media_executions_provider_job_id", ["provider_job_id"]),
        ("ix_identity_media_executions_secondary_provider_job_id", ["secondary_provider_job_id"]),
        ("ix_identity_media_executions_lease_owner", ["lease_owner"]),
        ("ix_identity_media_executions_lease_expires_at", ["lease_expires_at"]),
        ("ix_identity_media_executions_available_at", ["available_at"]),
        ("ix_identity_media_executions_output_checksum_sha256", ["output_checksum_sha256"]),
        ("ix_identity_media_executions_org_status_created", ["organization_id", "status", "created_at"]),
        ("ix_identity_media_executions_claim", ["status", "available_at", "created_at"]),
        ("ix_identity_media_executions_provider_state_lookup", ["provider", "provider_state"]),
        ("ix_identity_media_executions_user_created", ["requested_by_id", "created_at"]),
    )
    for name, fields in definitions:
        if name not in indexes:
            op.create_index(name, "identity_media_executions", fields)


def downgrade() -> None:
    bind = op.get_bind()
    if "identity_media_executions" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("identity_media_executions")
