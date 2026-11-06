"""Add the P3 unified inbox and Meta data-deletion schema.

Revision ID: 20261106_0068
Revises: 20261106_0067

Creates ``social_inbox_conversations`` (one comment thread or DM thread on an
OAuth-connected account, with read/unread, assignment, status and the
24-hour messaging window anchor), ``social_inbox_messages`` (comments,
replies and direct messages, unique per account and Meta id),
``social_webhook_events`` (idempotency ledger of signed Meta webhook changes)
and ``social_data_deletion_requests`` (Meta data-deletion and deauthorize
callbacks with their confirmation codes). Nothing existing is altered. The
downgrade drops exactly these four tables.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261106_0068"
down_revision = "20261106_0067"
branch_labels = None
depends_on = None

_TABLES = (
    "social_inbox_conversations",
    "social_inbox_messages",
    "social_webhook_events",
    "social_data_deletion_requests",
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _organization() -> sa.Column:
    return sa.Column(
        "organization_id",
        sa.String(36),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def _account() -> sa.Column:
    return sa.Column(
        "account_id",
        sa.String(36),
        sa.ForeignKey("growth_social_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    present = set(inspector.get_table_names()).intersection(_TABLES)
    if present == set(_TABLES):
        return
    if present:
        raise RuntimeError(
            "P3 social inbox schema is partially present; manual review is "
            f"required (tables={sorted(present)})"
        )

    op.create_table(
        "social_inbox_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        _organization(),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _account(),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("external_thread_ref", sa.String(255), nullable=False),
        sa.Column("object_ref", sa.String(128)),
        sa.Column("participant_ref", sa.String(128)),
        sa.Column("participant_name", sa.String(240)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("unread_count", sa.Integer(), nullable=False),
        sa.Column(
            "assigned_to_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True)),
        sa.Column("last_message_preview", sa.String(280), nullable=False),
        sa.Column("sentiment", sa.String(16), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "account_id", "external_thread_ref", name="uq_social_inbox_conversations_thread"
        ),
    )
    for column in ("organization_id", "user_id", "account_id", "assigned_to_id"):
        op.create_index(
            f"ix_social_inbox_conversations_{column}", "social_inbox_conversations", [column]
        )
    op.create_index(
        "ix_social_inbox_conversations_owner_last",
        "social_inbox_conversations",
        ["organization_id", "user_id", "last_message_at"],
    )

    op.create_table(
        "social_inbox_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("social_inbox_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _organization(),
        _account(),
        sa.Column("external_message_ref", sa.String(255), nullable=False),
        sa.Column("parent_ref", sa.String(255)),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("author_ref", sa.String(128)),
        sa.Column("author_name", sa.String(240)),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("removed", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "sent_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "account_id", "external_message_ref", name="uq_social_inbox_messages_external"
        ),
    )
    for column in ("conversation_id", "organization_id", "account_id", "sent_by_id"):
        op.create_index(f"ix_social_inbox_messages_{column}", "social_inbox_messages", [column])
    op.create_index(
        "ix_social_inbox_messages_conversation_sent",
        "social_inbox_messages",
        ["conversation_id", "sent_at"],
    )

    op.create_table(
        "social_webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(24), nullable=False),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("entry_ref", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("matched_accounts", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("provider", "event_key", name="uq_social_webhook_events_key"),
    )

    op.create_table(
        "social_data_deletion_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("confirmation_code", sa.String(32), nullable=False, unique=True),
        sa.Column("external_user_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("connections_revoked", sa.Integer(), nullable=False),
        sa.Column("accounts_cleared", sa.Integer(), nullable=False),
        sa.Column("conversations_deleted", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index(
        "ix_social_data_deletion_requests_external_user_digest",
        "social_data_deletion_requests",
        ["external_user_digest"],
    )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
