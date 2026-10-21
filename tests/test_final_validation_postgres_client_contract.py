"""The real backup smoke must use the service's PostgreSQL major version."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/final-validation.yml"


def backend_job() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("\n  backend-tests:\n", 1)[1].split("\n  frontend-build:\n", 1)[0]


def test_backend_runner_has_supported_postgresql_16_package():
    job = backend_job()
    assert "runs-on: ubuntu-24.04" in job
    assert "image: postgres:16-alpine" in job
    assert "sudo apt-get install --yes --no-install-recommends postgresql-client-16" in job
    assert 'echo "/usr/lib/postgresql/16/bin" >> "$GITHUB_PATH"' in job
    assert job.index("Install PostgreSQL 16 client tools") < job.index("Run database migrations")


@pytest.mark.parametrize("tool", ["pg_dump", "pg_restore", "psql", "createdb", "dropdb"])
def test_each_client_is_version_checked_before_real_backup_smoke(tool):
    job = backend_job()
    guard = job.split("- name: Verify backup tools match PostgreSQL service", 1)[1].split("      - uses:", 1)[0]
    assert "set -euo pipefail" in guard
    assert tool in guard.split("for tool in ", 1)[1].split("; do", 1)[0].split()
    assert 'test "$executable" = "/usr/lib/postgresql/16/bin/$tool"' in guard
    assert r"\(PostgreSQL\) 16(\.|$)" in guard
    assert "|| true" not in guard
    assert "continue-on-error" not in guard
    assert job.index("Verify backup tools match PostgreSQL service") < job.index("Run backend tests with coverage")


def test_real_restore_smoke_and_failure_gates_are_not_disabled():
    job = backend_job()
    assert 'RUN_LIVE_BACKUP_SMOKE: "1"' in job
    assert "python -m pytest -vv tests" in job
    assert "--maxfail=1" in job
    assert "--cov-fail-under=22" in job
    assert "continue-on-error" not in job
    assert "-k not" not in job
