"""Add durable consent-gated realtime recording runtime state.

Revision ID: 20260905_0044
Revises: 20260825_0043
Create Date: 2026-09-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0044"
down_revision: str | None = "20260825_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required = {
        "organizations",
        "users",
        "realtime_tenant_quotas",
        "realtime_rooms",
        "realtime_participants",
        "studio_jobs",
        "studio_assets",
    }
    if not required.issubset(tables):
        raise RuntimeError("Realtime recording runtime requires Phase 36H and Studio tables")

    # New tenants receive bounded recording capacity. Existing explicit quota rows
    # are intentionally not changed because zero may be an Owner policy decision.
    op.alter_column(
        "realtime_tenant_quotas",
        "max_concurrent_recordings",
        existing_type=sa.Integer(),
        server_default=sa.text("2"),
        existing_nullable=False,
    )

    if "realtime_recordings" not in tables:
        op.create_table(
            "realtime_recordings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("room_id", sa.String(36), nullable=False),
            sa.Column("requested_by_id", sa.String(36), nullable=False),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="awaiting_consent"),
            sa.Column("provider_adapter", sa.String(40), nullable=False, server_default="livekit"),
            sa.Column("provider_egress_id", sa.String(160), nullable=True),
            sa.Column("output_format", sa.String(16), nullable=False, server_default="mp4"),
            sa.Column("output_relpath", sa.Text(), nullable=False),
            sa.Column("media_type", sa.String(120), nullable=False, server_default="video/mp4"),
            sa.Column("consent_version", sa.String(80), nullable=False),
            sa.Column("required_consent_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consented_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consent_digest_sha256", sa.String(64), nullable=True),
            sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
            sa.Column("output_checksum_sha256", sa.String(64), nullable=True),
            sa.Column("output_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("output_duration_ms", sa.BigInteger(), nullable=True),
            sa.Column("studio_job_id", sa.String(36), sa.ForeignKey("studio_jobs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("studio_asset_id", sa.String(36), sa.ForeignKey("studio_assets.id", ondelete="SET NULL"), nullable=True),
            sa.Column("provider_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("error_code", sa.String(120), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("id", "organization_id", name="uq_realtime_recording_id_org"),
            sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_realtime_recording_org_idempotency"),
            sa.UniqueConstraint("provider_egress_id", name="uq_realtime_recording_provider_egress"),
            sa.ForeignKeyConstraint(["room_id", "organization_id"], ["realtime_rooms.id", "realtime_rooms.organization_id"], name="fk_realtime_recording_room_tenant", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["requested_by_id", "organization_id"], ["users.id", "users.organization_id"], name="fk_realtime_recording_requester_tenant", ondelete="RESTRICT"),
        )
        for name, columns in (
            ("ix_realtime_recordings_organization_id", ["organization_id"]),
            ("ix_realtime_recordings_room_id", ["room_id"]),
            ("ix_realtime_recordings_requested_by_id", ["requested_by_id"]),
            ("ix_realtime_recordings_status", ["status"]),
            ("ix_realtime_recordings_provider_egress_id", ["provider_egress_id"]),
            ("ix_realtime_recordings_output_checksum_sha256", ["output_checksum_sha256"]),
            ("ix_realtime_recordings_studio_job_id", ["studio_job_id"]),
            ("ix_realtime_recordings_studio_asset_id", ["studio_asset_id"]),
            ("ix_realtime_recordings_org_room_status", ["organization_id", "room_id", "status"]),
            ("ix_realtime_recordings_org_status_created", ["organization_id", "status", "created_at"]),
        ):
            op.create_index(name, "realtime_recordings", columns)

    tables = set(sa.inspect(bind).get_table_names())
    if "realtime_recording_consents" not in tables:
        op.create_table(
            "realtime_recording_consents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("recording_id", sa.String(36), nullable=False),
            sa.Column("participant_id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("consent_version", sa.String(80), nullable=False),
            sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("recording_id", "participant_id", name="uq_realtime_recording_consent_participant"),
            sa.ForeignKeyConstraint(["recording_id", "organization_id"], ["realtime_recordings.id", "realtime_recordings.organization_id"], name="fk_realtime_recording_consent_recording_tenant", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["participant_id", "organization_id"], ["realtime_participants.id", "realtime_participants.organization_id"], name="fk_realtime_recording_consent_participant_tenant", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id", "organization_id"], ["users.id", "users.organization_id"], name="fk_realtime_recording_consent_user_tenant", ondelete="RESTRICT"),
        )
        for name, columns in (
            ("ix_realtime_recording_consents_organization_id", ["organization_id"]),
            ("ix_realtime_recording_consents_recording_id", ["recording_id"]),
            ("ix_realtime_recording_consents_participant_id", ["participant_id"]),
            ("ix_realtime_recording_consents_user_id", ["user_id"]),
            ("ix_realtime_recording_consents_status", ["status"]),
            ("ix_realtime_recording_consents_org_recording_status", ["organization_id", "recording_id", "status"]),
        ):
            op.create_index(name, "realtime_recording_consents", columns)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "realtime_recording_consents" in tables:
        op.drop_table("realtime_recording_consents")
    if "realtime_recordings" in tables:
        op.drop_table("realtime_recordings")
    if "realtime_tenant_quotas" in tables:
        op.alter_column(
            "realtime_tenant_quotas",
            "max_concurrent_recordings",
            existing_type=sa.Integer(),
            server_default=sa.text("0"),
            existing_nullable=False,
        )
