"""Harden GS-12 runtime authorization and single-scope live arming.

Revision ID: 20260815_0026
Revises: 20260815_0025
"""

from alembic import op
import sqlalchemy as sa

revision = "20260815_0026"
down_revision = "20260815_0025"
branch_labels = None
depends_on = None

TABLE = "growth_controlled_pilots"
INDEX = "uq_growth_controlled_pilots_live_scope"


def _indexes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return set()
    return {str(item.get("name")) for item in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    if INDEX in _indexes():
        return
    op.create_index(
        INDEX,
        TABLE,
        ["provider", "scope_ref"],
        unique=True,
        postgresql_where=sa.text("real_spend_allowed IS TRUE"),
    )


def downgrade() -> None:
    if INDEX in _indexes():
        op.drop_index(INDEX, table_name=TABLE)
