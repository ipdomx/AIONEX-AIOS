"""Add the P3 social publishing schema (posts, targets, attempts, uploads).

Revision ID: 20261106_0067
Revises: 20261106_0066

Creates ``social_media_uploads`` (composer uploads in private media storage),
``social_posts`` (a composed post with its schedule, timezone and retry
policy), ``social_post_targets`` (one connected account's publish job, lease,
idempotency key and Graph result) and ``social_post_attempts`` (append-only
attempt log). Nothing existing is altered. The downgrade drops exactly these
four tables.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261106_0067"
down_revision = "20261106_0066"
branch_labels = None
depends_on = None

_TABLES = (
    "social_media_uploads",
    "social_posts",
    "social_post_targets",
    "social_post_attempts",
)


def _owner_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    ]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    present = set(inspector.get_table_names()).intersection(_TABLES)
    if present == set(_TABLES):
        return
    if present:
        raise RuntimeError(
            "P3 social publishing schema is partially present; manual review is "
            f"required (tables={sorted(present)})"
        )

    op.create_table(
        "social_media_uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        *_owner_columns(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("storage_backend", sa.String(24), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_social_media_uploads_organization_id", "social_media_uploads", ["organization_id"]
    )
    op.create_index("ix_social_media_uploads_user_id", "social_media_uploads", ["user_id"])
    op.create_index(
        "ix_social_media_uploads_org_user_created",
        "social_media_uploads",
        ["organization_id", "user_id", "created_at"],
    )

    op.create_table(
        "social_posts",
        sa.Column("id", sa.String(36), primary_key=True),
        *_owner_columns(),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("post_type", sa.String(16), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("link_url", sa.String(2048)),
        sa.Column("media", sa.JSON(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("retry_policy", sa.JSON(), nullable=False),
        sa.Column("client_idempotency_key", sa.String(80)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "user_id", "client_idempotency_key", name="uq_social_posts_user_idempotency"
        ),
    )
    op.create_index("ix_social_posts_organization_id", "social_posts", ["organization_id"])
    op.create_index("ix_social_posts_user_id", "social_posts", ["user_id"])
    op.create_index(
        "ix_social_posts_org_user_scheduled",
        "social_posts",
        ["organization_id", "user_id", "scheduled_at"],
    )
    op.create_index(
        "ix_social_posts_status_scheduled", "social_posts", ["status", "scheduled_at"]
    )

    op.create_table(
        "social_post_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "post_id",
            sa.String(36),
            sa.ForeignKey("social_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_owner_columns(),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("growth_social_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("account_name", sa.String(240), nullable=False),
        sa.Column("overrides", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True)),
        sa.Column("container_id", sa.String(64)),
        sa.Column("remote_post_id", sa.String(128)),
        sa.Column("permalink", sa.String(1024)),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("post_id", "account_id", name="uq_social_post_targets_post_account"),
        sa.UniqueConstraint("idempotency_key", name="uq_social_post_targets_idempotency_key"),
    )
    op.create_index("ix_social_post_targets_post_id", "social_post_targets", ["post_id"])
    op.create_index(
        "ix_social_post_targets_organization_id", "social_post_targets", ["organization_id"]
    )
    op.create_index("ix_social_post_targets_user_id", "social_post_targets", ["user_id"])
    op.create_index("ix_social_post_targets_account_id", "social_post_targets", ["account_id"])
    op.create_index(
        "ix_social_post_targets_status_next",
        "social_post_targets",
        ["status", "next_attempt_at"],
    )

    op.create_table(
        "social_post_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "target_id",
            sa.String(36),
            sa.ForeignKey("social_post_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("transient", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("remote_post_id", sa.String(128)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("target_id", "attempt_number", name="uq_social_post_attempts_number"),
    )
    op.create_index("ix_social_post_attempts_target_id", "social_post_attempts", ["target_id"])
    op.create_index(
        "ix_social_post_attempts_organization_id", "social_post_attempts", ["organization_id"]
    )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
