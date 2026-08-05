from __future__ import annotations

import pytest

from tests import conftest as database_guard


def _clear_database_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "POSTGRES_DB",
        "ENVIRONMENT",
        "AIOS_ALLOW_DISPOSABLE_PRODUCTION_TESTS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_guard_rejects_production_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_database_environment(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("POSTGRES_DB", "aionex")

    with pytest.raises(pytest.UsageError, match="Refusing to run backend tests"):
        database_guard._assert_safe_test_database()


def test_guard_rejects_non_test_database_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_database_environment(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://tester:tester@localhost:5432/aionex",
    )

    with pytest.raises(pytest.UsageError, match="non-test database"):
        database_guard._assert_safe_test_database()


def test_guard_allows_explicit_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_database_environment(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://tester:tester@localhost:5432/aionex_test",
    )

    database_guard._assert_safe_test_database()


def test_guard_allows_disposable_ci_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_database_environment(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("POSTGRES_DB", "aionex")
    monkeypatch.setenv("AIOS_ALLOW_DISPOSABLE_PRODUCTION_TESTS", "1")

    database_guard._assert_safe_test_database()
