"""Durable off-site backup replication evidence.

Revision ID: 20260907_0045
Revises: 20260905_0044
"""
from alembic import op
import sqlalchemy as sa

revision = "20260907_0045"
down_revision = "20260905_0044"
branch_labels = None
depends_on = None
_COLUMNS = {"offsite_status", "offsite_evidence", "offsite_completed_at"}


def upgrade() -> None:
    # Historical revision 0001 calls current Base.metadata.create_all(), so a fresh
    # database can already contain these columns. Existing Production at 0044 does
    # not. Accept all-present, fail closed on partial presence.
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("backup_records")}
    present = columns & _COLUMNS
    if present == _COLUMNS:
        return
    if present:
        raise RuntimeError(
            "Off-site backup evidence columns are partially present; manual review is required "
            f"before migration (present={sorted(present)})"
        )
    op.add_column("backup_records", sa.Column("offsite_status", sa.String(length=32), nullable=False, server_default="disabled"))
    op.add_column("backup_records", sa.Column("offsite_evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("backup_records", sa.Column("offsite_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_backup_records_offsite_status", "backup_records", ["offsite_status"], unique=False)
    op.alter_column("backup_records", "offsite_status", server_default=None)
    op.alter_column("backup_records", "offsite_evidence", server_default=None)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("backup_records")}
    if "offsite_status" in columns:
        indexes = {item["name"] for item in inspector.get_indexes("backup_records")}
        if "ix_backup_records_offsite_status" in indexes:
            op.drop_index("ix_backup_records_offsite_status", table_name="backup_records")
    for name in ("offsite_completed_at", "offsite_evidence", "offsite_status"):
        if name in columns:
            op.drop_column("backup_records", name)
