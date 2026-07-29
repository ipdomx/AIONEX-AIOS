"""Helpers shared by the Alembic migration environment and its tests."""

from __future__ import annotations

# A stable, application-specific PostgreSQL advisory lock used to serialize
# concurrent ``alembic upgrade`` processes during rolling deployments.
MIGRATION_ADVISORY_LOCK_ID = 1_095_327_059


def render_alembic_config_url(database_url: str) -> str:
    """Escape ConfigParser interpolation markers without changing the URL."""
    return database_url.replace("%", "%%")
