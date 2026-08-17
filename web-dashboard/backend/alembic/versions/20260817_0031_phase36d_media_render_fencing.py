"""Harden Phase 36D media render leases with expiry and fencing.

Revision ID: 20260817_0031
Revises: 20260817_0030
"""
from alembic import op
import sqlalchemy as sa

revision = "20260817_0031"
down_revision = "20260817_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "media_render_steps" not in tables:
        raise RuntimeError("Phase 36D render fencing requires media_render_steps")
    columns = {item["name"] for item in inspector.get_columns("media_render_steps")}
    additions = (
        ("lease_owner", sa.Column("lease_owner", sa.String(160))),
        ("lease_expires_at", sa.Column("lease_expires_at", sa.DateTime(timezone=True))),
        ("fencing_token", sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0")),
        ("available_at", sa.Column("available_at", sa.DateTime(timezone=True))),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("media_render_steps", column)
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("media_render_steps")}
    for name, fields in (
        ("ix_media_render_steps_lease_owner", ["lease_owner"]),
        ("ix_media_render_steps_lease_expires_at", ["lease_expires_at"]),
        ("ix_media_render_steps_available_at", ["available_at"]),
        ("ix_media_render_steps_recovery", ["status", "lease_expires_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "media_render_steps", fields)


def downgrade() -> None:
    bind = op.get_bind()
    if "media_render_steps" not in set(sa.inspect(bind).get_table_names()):
        return
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("media_render_steps")}
    for name in (
        "ix_media_render_steps_recovery",
        "ix_media_render_steps_available_at",
        "ix_media_render_steps_lease_expires_at",
        "ix_media_render_steps_lease_owner",
    ):
        if name in indexes:
            op.drop_index(name, table_name="media_render_steps")
    columns = {item["name"] for item in sa.inspect(bind).get_columns("media_render_steps")}
    for name in ("available_at", "fencing_token", "lease_expires_at", "lease_owner"):
        if name in columns:
            op.drop_column("media_render_steps", name)
