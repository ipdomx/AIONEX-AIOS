"""Add GS-06 compliant lead intelligence persistence.

Revision ID: 20260814_0021
Revises: 20260814_0020
"""

from alembic import op
import sqlalchemy as sa

revision = "20260814_0021"
down_revision = "20260814_0020"
branch_labels = None
depends_on = None

_TABLES = {
    "growth_lead_records",
    "growth_lead_provenance",
    "growth_lead_consents",
    "growth_lead_suppressions",
}


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing.intersection(_TABLES)
    if present == _TABLES:
        return
    if present:
        raise RuntimeError(
            "GS-06 lead schema is partially present; manual review is required "
            f"before migration (present={sorted(present)})"
        )
    op.create_table(
        "growth_lead_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(240)),
        sa.Column("email_normalized", sa.String(320)),
        sa.Column("phone_normalized", sa.String(64)),
        sa.Column("company_name", sa.String(240)),
        sa.Column("country_code", sa.String(2)),
        sa.Column("dedupe_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True)),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "dedupe_fingerprint",
            name="uq_growth_lead_org_fingerprint",
        ),
    )
    op.create_index(
        "ix_growth_leads_org_status_created",
        "growth_lead_records",
        ["organization_id", "status", "created_at"],
    )
    op.create_index(
        "ix_growth_lead_records_organization_id",
        "growth_lead_records",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_lead_records_created_by_id", "growth_lead_records", ["created_by_id"]
    )
    op.create_index(
        "ix_growth_lead_records_email_normalized",
        "growth_lead_records",
        ["email_normalized"],
    )
    op.create_index(
        "ix_growth_lead_records_phone_normalized",
        "growth_lead_records",
        ["phone_normalized"],
    )
    op.create_index(
        "ix_growth_lead_records_dedupe_fingerprint",
        "growth_lead_records",
        ["dedupe_fingerprint"],
    )
    op.create_index("ix_growth_lead_records_status", "growth_lead_records", ["status"])
    op.create_index(
        "ix_growth_lead_records_retention_until",
        "growth_lead_records",
        ["retention_until"],
    )

    op.create_table(
        "growth_lead_provenance",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.String(36),
            sa.ForeignKey("growth_lead_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(48), nullable=False),
        sa.Column("source_ref", sa.String(500)),
        sa.Column("collection_method", sa.String(64), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_lead_provenance_lead_created",
        "growth_lead_provenance",
        ["lead_id", "created_at"],
    )
    op.create_index(
        "ix_growth_lead_provenance_organization_id",
        "growth_lead_provenance",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_lead_provenance_lead_id", "growth_lead_provenance", ["lead_id"]
    )
    op.create_index(
        "ix_growth_lead_provenance_source_type",
        "growth_lead_provenance",
        ["source_type"],
    )

    op.create_table(
        "growth_lead_consents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.String(36),
            sa.ForeignKey("growth_lead_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("lawful_basis", sa.String(48), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "lead_id", "purpose", "lawful_basis", name="uq_growth_lead_consent_basis"
        ),
    )
    op.create_index(
        "ix_growth_lead_consents_lead_status",
        "growth_lead_consents",
        ["lead_id", "status"],
    )
    op.create_index(
        "ix_growth_lead_consents_organization_id",
        "growth_lead_consents",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_lead_consents_lead_id", "growth_lead_consents", ["lead_id"]
    )
    op.create_index(
        "ix_growth_lead_consents_status", "growth_lead_consents", ["status"]
    )
    op.create_index(
        "ix_growth_lead_consents_expires_at", "growth_lead_consents", ["expires_at"]
    )

    op.create_table(
        "growth_lead_suppressions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            sa.String(36),
            sa.ForeignKey("growth_lead_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "lead_id",
            "channel",
            name="uq_growth_lead_suppression_channel",
        ),
    )
    op.create_index(
        "ix_growth_lead_suppressions_org_channel",
        "growth_lead_suppressions",
        ["organization_id", "channel"],
    )
    op.create_index(
        "ix_growth_lead_suppressions_organization_id",
        "growth_lead_suppressions",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_lead_suppressions_lead_id", "growth_lead_suppressions", ["lead_id"]
    )


def downgrade() -> None:
    op.drop_table("growth_lead_suppressions")
    op.drop_table("growth_lead_consents")
    op.drop_table("growth_lead_provenance")
    op.drop_table("growth_lead_records")
