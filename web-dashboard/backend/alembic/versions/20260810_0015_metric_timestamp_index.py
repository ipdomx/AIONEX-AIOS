"""Add standalone timestamp index for operational metric retention and time-range queries.

Revision ID: 20260810_0015
Revises: 20260809_0014
"""
from alembic import op
import sqlalchemy as sa

revision = "20260810_0015"
down_revision = "20260809_0014"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_metric_samples_timestamp"
_TABLE = "metric_samples"


def _indexes() -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_indexes(_TABLE)
        if item.get("name")
    }


def upgrade() -> None:
    if _INDEX_NAME not in _indexes():
        op.create_index(_INDEX_NAME, _TABLE, ["timestamp"])


def downgrade() -> None:
    if _INDEX_NAME in _indexes():
        op.drop_index(_INDEX_NAME, table_name=_TABLE)
