"""Initial consolidated AIOS dashboard schema.

Revision ID: 20260726_0001
Revises:
Create Date: 2026-07-26
"""

from alembic import op

from app.db.base import Base
from app.db import models  # noqa: F401

revision = "20260726_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
