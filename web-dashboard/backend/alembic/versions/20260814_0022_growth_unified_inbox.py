"""Add GS-07 unified inbox and CRM workflow persistence.

Revision ID: 20260814_0022
Revises: 20260814_0021
"""

from alembic import op
import sqlalchemy as sa

revision = "20260814_0022"
down_revision = "20260814_0021"
branch_labels = None
depends_on = None

_TABLES = {
    "growth_inbox_threads",
    "growth_inbox_messages",
    "growth_inbox_notes",
    "growth_quick_reply_drafts",
}


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    present = existing.intersection(_TABLES)
    if present == _TABLES:
        return
    if present:
        raise RuntimeError(
            "GS-07 inbox schema is partially present; manual review is required "
            f"before migration (present={sorted(present)})"
        )

    op.create_table(
        "growth_inbox_threads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("growth_social_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "lead_id",
            sa.String(36),
            sa.ForeignKey("growth_lead_records.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("external_thread_ref", sa.String(240), nullable=False),
        sa.Column("thread_type", sa.String(32), nullable=False),
        sa.Column("participant_ref", sa.String(240)),
        sa.Column("participant_name", sa.String(240)),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "assigned_to_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("sentiment", sa.String(24), nullable=False, server_default="neutral"),
        sa.Column("spam_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "account_id",
            "external_thread_ref",
            name="uq_growth_inbox_thread_external",
        ),
    )
    op.create_index(
        "ix_growth_inbox_threads_org_status_updated",
        "growth_inbox_threads",
        ["organization_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_growth_inbox_threads_org_assignee_updated",
        "growth_inbox_threads",
        ["organization_id", "assigned_to_id", "updated_at"],
    )

    op.create_table(
        "growth_inbox_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.String(36),
            sa.ForeignKey("growth_inbox_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_message_ref", sa.String(240), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("author_ref", sa.String(240)),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sentiment", sa.String(24), nullable=False, server_default="neutral"),
        sa.Column("spam_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("provider_event", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "thread_id", "external_message_ref", name="uq_growth_inbox_message_external"
        ),
    )
    op.create_index(
        "ix_growth_inbox_messages_thread_created",
        "growth_inbox_messages",
        ["thread_id", "created_at"],
    )
    op.create_index(
        "ix_growth_inbox_messages_org_direction_created",
        "growth_inbox_messages",
        ["organization_id", "direction", "created_at"],
    )

    op.create_table(
        "growth_inbox_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.String(36),
            sa.ForeignKey("growth_inbox_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_inbox_notes_thread_created",
        "growth_inbox_notes",
        ["thread_id", "created_at"],
    )

    op.create_table(
        "growth_quick_reply_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.String(36),
            sa.ForeignKey("growth_inbox_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("template_key", sa.String(120)),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column(
            "ai_suggested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "approval_required", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "external_send_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_growth_quick_replies_thread_status_created",
        "growth_quick_reply_drafts",
        ["thread_id", "status", "created_at"],
    )


def downgrade() -> None:
    for table in (
        "growth_quick_reply_drafts",
        "growth_inbox_notes",
        "growth_inbox_messages",
        "growth_inbox_threads",
    ):
        op.drop_table(table)
