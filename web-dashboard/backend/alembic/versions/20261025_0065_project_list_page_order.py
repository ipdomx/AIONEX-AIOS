"""Add the authenticated-tenant project page order index.

Revision ID: 20261025_0065
Revises: 20260920_0064

The bounded first-page query reads (organization_id, created_at DESC). Build
concurrently so existing tenant project writes are not locked during upgrade.
It changes no project rows, permissions, ownership or billing.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261025_0065"
down_revision = "20260920_0064"
branch_labels = None
depends_on = None

INDEX = "ix_projects_org_created_at_desc"


def _inspect_index(bind) -> tuple[str, bool, bool] | None:
    result = bind.execute(
        sa.text(
            """
            SELECT pg_get_indexdef(i.indexrelid), i.indisvalid, i.indisready
            FROM pg_index AS i
            JOIN pg_class AS c ON c.oid = i.indexrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = :index_name
            """
        ),
        {"index_name": INDEX},
    ).one_or_none()
    if result is None:
        return None
    return str(result[0]), bool(result[1]), bool(result[2])


def _require_expected(definition: tuple[str, bool, bool] | None) -> None:
    if definition is None:
        raise RuntimeError("FR09 project pagination index missing")
    description, valid, ready = definition
    normalized = " ".join(description.lower().split())
    required = "on public.projects using btree (organization_id, created_at desc)"
    if required not in normalized or not valid or not ready:
        raise RuntimeError("FR09 project pagination index has unexpected definition or state")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("FR09 project index requires PostgreSQL")
    existing = _inspect_index(bind)
    if existing is not None:
        _require_expected(existing)
        return
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_projects_org_created_at_desc "
            "ON public.projects (organization_id, created_at DESC)"
        )
    _require_expected(_inspect_index(op.get_bind()))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("FR09 project index requires PostgreSQL")
    existing = _inspect_index(bind)
    if existing is not None:
        _require_expected(existing)
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.ix_projects_org_created_at_desc")
