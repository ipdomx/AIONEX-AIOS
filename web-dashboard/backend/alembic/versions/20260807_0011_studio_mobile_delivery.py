"""Complete Production Studio and mobile delivery persistence.

Revision ID: 20260807_0011
Revises: 20260807_0010
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.db import models  # noqa: F401
from app.db.base import Base

revision = "20260807_0011"
down_revision = "20260807_0010"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "studio_jobs",
    "studio_assets",
    "studio_asset_revisions",
    "studio_safety_reviews",
    "project_studio_attachments",
    "mobile_releases",
    "mobile_release_artifacts",
    "mobile_validation_runs",
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    metadata = Base.metadata
    for table_name in NEW_TABLES:
        metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    tables = _tables()
    for table_name in reversed(NEW_TABLES):
        if table_name in tables:
            op.drop_table(table_name)
