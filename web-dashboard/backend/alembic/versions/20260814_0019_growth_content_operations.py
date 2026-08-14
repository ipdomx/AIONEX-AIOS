"""Add GS-04 content operations persistence.

Revision ID: 20260814_0019
Revises: 20260814_0018
"""

from alembic import op
import sqlalchemy as sa

revision = "20260814_0019"
down_revision = "20260814_0018"
branch_labels = None
depends_on = None

_TABLES = (
    "growth_content_items",
    "growth_content_variants",
    "growth_content_schedules",
    "growth_content_publish_simulations",
)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing.intersection(_TABLES)
    if present == set(_TABLES):
        return
    if present:
        raise RuntimeError(
            "GS-04 content schema is partially present; manual review is required "
            f"before migration (present={sorted(present)})"
        )

    op.create_table(
        "growth_content_items",
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
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("base_text", sa.Text(), nullable=False),
        sa.Column("link_url", sa.Text()),
        sa.Column("media_refs", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("approval_status", sa.String(32), nullable=False),
        sa.Column(
            "approved_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approval_note", sa.Text()),
        sa.Column("recycle_count", sa.Integer(), nullable=False),
        sa.Column("content_metadata", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_content_items_organization_id",
        "growth_content_items",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_content_items_created_by_id",
        "growth_content_items",
        ["created_by_id"],
    )
    op.create_index(
        "ix_growth_content_items_project_id", "growth_content_items", ["project_id"]
    )
    op.create_index(
        "ix_growth_content_items_approved_by_id",
        "growth_content_items",
        ["approved_by_id"],
    )
    op.create_index(
        "ix_growth_content_items_status", "growth_content_items", ["status"]
    )
    op.create_index(
        "ix_growth_content_items_org_status_created",
        "growth_content_items",
        ["organization_id", "status", "created_at"],
    )

    op.create_table(
        "growth_content_variants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.String(36),
            sa.ForeignKey("growth_content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("growth_social_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("link_url", sa.Text()),
        sa.Column("media_refs", sa.JSON(), nullable=False),
        sa.Column("hashtags", sa.JSON(), nullable=False),
        sa.Column("mentions", sa.JSON(), nullable=False),
        sa.Column("platform_overrides", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "content_id",
            "provider",
            "account_id",
            name="uq_growth_content_variant_target",
        ),
    )
    op.create_index(
        "ix_growth_content_variants_organization_id",
        "growth_content_variants",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_content_variants_content_id",
        "growth_content_variants",
        ["content_id"],
    )
    op.create_index(
        "ix_growth_content_variants_account_id",
        "growth_content_variants",
        ["account_id"],
    )
    op.create_index(
        "ix_growth_content_variants_provider", "growth_content_variants", ["provider"]
    )
    op.create_index(
        "ix_growth_content_variants_content_provider",
        "growth_content_variants",
        ["content_id", "provider"],
    )

    op.create_table(
        "growth_content_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.String(36),
            sa.ForeignKey("growth_content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.String(36),
            sa.ForeignKey("growth_content_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("growth_social_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("recurrence", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column(
            "recycle_of_schedule_id",
            sa.String(36),
            sa.ForeignKey("growth_content_schedules.id", ondelete="SET NULL"),
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("simulated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_content_schedules_organization_id",
        "growth_content_schedules",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_content_schedules_content_id",
        "growth_content_schedules",
        ["content_id"],
    )
    op.create_index(
        "ix_growth_content_schedules_variant_id",
        "growth_content_schedules",
        ["variant_id"],
    )
    op.create_index(
        "ix_growth_content_schedules_account_id",
        "growth_content_schedules",
        ["account_id"],
    )
    op.create_index(
        "ix_growth_content_schedules_provider", "growth_content_schedules", ["provider"]
    )
    op.create_index(
        "ix_growth_content_schedules_scheduled_for",
        "growth_content_schedules",
        ["scheduled_for"],
    )
    op.create_index(
        "ix_growth_content_schedules_status", "growth_content_schedules", ["status"]
    )
    op.create_index(
        "ix_growth_content_schedules_recycle_of_schedule_id",
        "growth_content_schedules",
        ["recycle_of_schedule_id"],
    )
    op.create_index(
        "ix_growth_content_schedules_due",
        "growth_content_schedules",
        ["status", "scheduled_for", "priority"],
    )
    op.create_index(
        "ix_growth_content_schedules_content_created",
        "growth_content_schedules",
        ["content_id", "created_at"],
    )

    op.create_table(
        "growth_content_publish_simulations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "schedule_id",
            sa.String(36),
            sa.ForeignKey("growth_content_schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.String(36),
            sa.ForeignKey("growth_content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.String(36),
            sa.ForeignKey("growth_content_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("growth_social_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("utm_url", sa.Text()),
        sa.Column("live_publish_allowed", sa.Boolean(), nullable=False),
        sa.Column("simulated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_content_publish_organization_id",
        "growth_content_publish_simulations",
        ["organization_id"],
    )
    op.create_index(
        "ix_growth_content_publish_schedule_id",
        "growth_content_publish_simulations",
        ["schedule_id"],
    )
    op.create_index(
        "ix_growth_content_publish_content_id",
        "growth_content_publish_simulations",
        ["content_id"],
    )
    op.create_index(
        "ix_growth_content_publish_variant_id",
        "growth_content_publish_simulations",
        ["variant_id"],
    )
    op.create_index(
        "ix_growth_content_publish_account_id",
        "growth_content_publish_simulations",
        ["account_id"],
    )
    op.create_index(
        "ix_growth_content_publish_provider",
        "growth_content_publish_simulations",
        ["provider"],
    )
    op.create_index(
        "ix_growth_content_publish_status",
        "growth_content_publish_simulations",
        ["status"],
    )
    op.create_index(
        "ix_growth_content_publish_fingerprint",
        "growth_content_publish_simulations",
        ["fingerprint"],
    )
    op.create_index(
        "ix_growth_content_publish_schedule_created",
        "growth_content_publish_simulations",
        ["schedule_id", "created_at"],
    )
    op.create_index(
        "ix_growth_content_publish_org_status",
        "growth_content_publish_simulations",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("growth_content_publish_simulations")
    op.drop_table("growth_content_schedules")
    op.drop_table("growth_content_variants")
    op.drop_table("growth_content_items")
