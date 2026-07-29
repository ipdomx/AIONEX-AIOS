"""Compatibility facade for the consolidated, Alembic-managed database."""

from functools import lru_cache
from pathlib import Path
from typing import AsyncGenerator

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from app.core.logging import get_logger
from app.db.base import SessionLocal, engine

logger = get_logger(__name__)

AsyncSessionLocal = SessionLocal

# Retained only for legacy model imports. Runtime tables are defined by
# app.db.base.Base and must be created exclusively through Alembic.
Base = declarative_base()

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def expected_alembic_heads() -> frozenset[str]:
    """Return the immutable set of schema heads shipped with this backend."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def current_alembic_heads(connection: Connection) -> frozenset[str]:
    """Read all applied heads from an existing synchronous SQLAlchemy connection."""
    migration_context = MigrationContext.configure(connection)
    return frozenset(migration_context.get_current_heads())


async def init_db():
    """Fail fast unless the Alembic-managed schema matches the shipped head."""
    expected_heads = expected_alembic_heads()
    async with engine.connect() as connection:
        current_heads = await connection.run_sync(current_alembic_heads)

    if not expected_heads:
        raise RuntimeError("No Alembic head is defined for the backend schema")
    if current_heads != expected_heads:
        current_label = ", ".join(sorted(current_heads)) or "unmigrated"
        expected_label = ", ".join(sorted(expected_heads))
        raise RuntimeError(
            "Database schema is not at the required Alembic head "
            f"(current: {current_label}; expected: {expected_label}); "
            "run `alembic upgrade head`"
        )
    logger.info(
        "Database schema verified",
        revisions=",".join(sorted(current_heads)),
    )


async def close_db():
    """Close database connections."""
    await engine.dispose()
    logger.info("Database engine disposed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
