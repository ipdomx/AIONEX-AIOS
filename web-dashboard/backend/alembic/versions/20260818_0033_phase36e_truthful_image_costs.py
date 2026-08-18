"""Make Phase 36E image cost evidence truthful.

Revision ID: 20260818_0033
Revises: 20260818_0032
"""
from alembic import op
import sqlalchemy as sa

revision = "20260818_0033"
down_revision = "20260818_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "design_image_executions" not in set(inspector.get_table_names()):
        raise RuntimeError("Phase 36E cost migration requires design_image_executions")
    columns = {item["name"]: item for item in inspector.get_columns("design_image_executions")}
    if "actual_cost_usd" not in columns:
        raise RuntimeError("Phase 36E cost migration requires actual_cost_usd")
    if not bool(columns["actual_cost_usd"].get("nullable")):
        op.alter_column("design_image_executions", "actual_cost_usd", existing_type=sa.Float(), nullable=True)
    if "cost_basis" not in columns:
        op.add_column(
            "design_image_executions",
            sa.Column("cost_basis", sa.String(64), nullable=False, server_default="unknown"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "design_image_executions" not in set(inspector.get_table_names()):
        return
    columns = {item["name"]: item for item in inspector.get_columns("design_image_executions")}
    if "cost_basis" in columns:
        op.drop_column("design_image_executions", "cost_basis")
    columns = {item["name"]: item for item in sa.inspect(bind).get_columns("design_image_executions")}
    if "actual_cost_usd" in columns and bool(columns["actual_cost_usd"].get("nullable")):
        op.execute(sa.text("UPDATE design_image_executions SET actual_cost_usd = 0 WHERE actual_cost_usd IS NULL"))
        op.alter_column("design_image_executions", "actual_cost_usd", existing_type=sa.Float(), nullable=False)
