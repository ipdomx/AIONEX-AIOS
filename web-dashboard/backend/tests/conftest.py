"""Global safety gate for backend tests.

The backend suite creates, mutates, suspends, and deletes database records.  It must
never inherit the live production database configuration from a running container.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.engine import make_url

_SAFE_DATABASE_MARKERS = ("test", "pytest", "ci", "smoke", "disposable")
_ALLOW_DISPOSABLE_ENV = "AIOS_ALLOW_DISPOSABLE_PRODUCTION_TESTS"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _configured_database_name() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        try:
            return (make_url(database_url).database or "").strip().lower()
        except (TypeError, ValueError):
            return ""
    return os.getenv("POSTGRES_DB", "").strip().lower()


def _assert_safe_test_database() -> None:
    """Abort before collection when pytest targets a non-test database."""

    if _truthy(os.getenv(_ALLOW_DISPOSABLE_ENV)):
        return

    environment = os.getenv("ENVIRONMENT", "").strip().lower()
    database_name = _configured_database_name()
    is_production_environment = environment in {"production", "prod"}
    is_explicit_test_database = bool(database_name) and any(
        marker in database_name for marker in _SAFE_DATABASE_MARKERS
    )

    if is_production_environment or (database_name and not is_explicit_test_database):
        raise pytest.UsageError(
            "Refusing to run backend tests against a production or non-test database. "
            "Use an isolated database whose name contains 'test', 'pytest', 'ci', "
            "'smoke', or 'disposable'. The explicit disposable override is reserved "
            "for short-lived CI containers only."
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    _assert_safe_test_database()
