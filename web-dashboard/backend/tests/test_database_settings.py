import hashlib
import os
from pathlib import Path
import subprocess
import tarfile

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db import database
from app.db.migration import render_alembic_config_url

VALID_SECRET = "database-settings-test-secret-key-123456789"


def test_database_url_is_derived_from_postgres_credentials() -> None:
    settings = Settings(
        _env_file=None,
        SECRET_KEY=VALID_SECRET,
        DATABASE_URL="",
        POSTGRES_HOST="postgres",
        POSTGRES_PORT=5432,
        POSTGRES_USER="aios_user",
        POSTGRES_PASSWORD="p@ss:/word",
        POSTGRES_DB="aionex",
    )

    url = make_url(settings.DATABASE_URL)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "postgres"
    assert url.port == 5432
    assert url.username == "aios_user"
    assert url.password == "p@ss:/word"
    assert url.database == "aionex"


def test_explicit_database_url_takes_precedence() -> None:
    explicit_url = "postgresql+asyncpg://external:secret@db.example:5433/external"
    settings = Settings(
        _env_file=None,
        SECRET_KEY=VALID_SECRET,
        DATABASE_URL=f"  {explicit_url}  ",
        POSTGRES_PASSWORD="ignored",
    )

    assert settings.DATABASE_URL == explicit_url


def test_alembic_config_accepts_percent_encoded_database_password() -> None:
    database_url = (
        "postgresql+asyncpg://aionex:"
        "p%40ss%3Aword%2Fwith%25percent@postgres:5432/aionex"
    )
    config = Config()

    config.set_main_option(
        "sqlalchemy.url",
        render_alembic_config_url(database_url),
    )

    assert config.get_main_option("sqlalchemy.url") == database_url
    assert make_url(config.get_main_option("sqlalchemy.url")).password == (
        "p@ss:word/with%percent"
    )


def test_postgres_recovery_script_has_valid_bash_syntax() -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "reconcile-postgres-credentials.sh"
    )
    subprocess.run(["bash", "-n", str(script)], check=True)


@pytest.mark.parametrize(
    ("compose_file", "env_file"),
    [
        ("", ""),
        ("docker-compose.production.yml", ".env.production.example"),
    ],
)
def test_postgres_recovery_script_uses_one_compose_contract(
    tmp_path: Path,
    compose_file: str,
    env_file: str,
) -> None:
    dashboard_root = Path(__file__).resolve().parents[2]
    script = dashboard_root / "scripts" / "reconcile-postgres-credentials.sh"
    fake_docker = tmp_path / "docker"
    call_log = tmp_path / "docker-calls.log"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "${DOCKER_CALL_LOG:?}"

if [[ "${1:-}" == "inspect" ]]; then
  echo healthy
  exit 0
fi

[[ "${1:-}" == "compose" ]] || exit 1
shift
if [[ "${1:-}" == "version" ]]; then
  exit 0
fi

while [[ "${1:-}" == "-f" || "${1:-}" == "--env-file" ]]; do
  shift 2
done

case "${1:-}" in
  config)
    printf 'postgres\npostgres-credential-reconciler\nbackend\n'
    if [[ "${HAS_BACKUP_WORKER:-false}" == "true" ]]; then
      printf 'backup-worker\n'
    fi
    ;;
  ps)
    echo "${3:-unknown}-container-id"
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["DOCKER_CALL_LOG"] = str(call_log)
    if compose_file:
        environment["COMPOSE_FILE"] = compose_file
    else:
        environment.pop("COMPOSE_FILE", None)
    if env_file:
        environment["ENV_FILE"] = env_file
    else:
        environment.pop("ENV_FILE", None)
    environment["HAS_BACKUP_WORKER"] = (
        "true" if compose_file == "docker-compose.production.yml" else "false"
    )

    subprocess.run(
        ["bash", str(script)],
        cwd=dashboard_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    wrapped_calls = [
        line
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("compose -f ")
    ]
    expected_prefix = f"compose -f {compose_file or 'docker-compose.yml'} "
    if env_file:
        expected_prefix += f"--env-file {(dashboard_root / env_file).resolve()} "

    expected_call_count = 10 if compose_file else 6
    assert len(wrapped_calls) == expected_call_count
    assert all(line.startswith(expected_prefix) for line in wrapped_calls)
    assert any(line.endswith("config --services") for line in wrapped_calls)
    assert any(line.endswith("up -d --no-deps postgres") for line in wrapped_calls)
    assert any(
        line.endswith("run --rm --no-deps postgres-credential-reconciler")
        for line in wrapped_calls
    )
    assert any(
        line.endswith("up -d --force-recreate backend") for line in wrapped_calls
    )
    assert any(line.endswith("ps -q backend") for line in wrapped_calls)
    if compose_file:
        assert any(
            line.endswith("ps --status running -q backup-worker")
            for line in wrapped_calls
        )
        assert any(line.endswith("stop backup-worker") for line in wrapped_calls)
        assert any(
            line.endswith("up -d --no-deps --force-recreate backup-worker")
            for line in wrapped_calls
        )
        assert any(line.endswith("ps -q backup-worker") for line in wrapped_calls)
    else:
        assert not any("backup-worker" in line for line in wrapped_calls)


@pytest.mark.parametrize(
    ("reconcile_exit_code", "ambiguous_mutation"),
    [(1, False), (2, True)],
)
def test_postgres_reconcile_failure_restores_dependents_safely(
    tmp_path: Path,
    reconcile_exit_code: int,
    ambiguous_mutation: bool,
) -> None:
    dashboard_root = Path(__file__).resolve().parents[2]
    script = dashboard_root / "scripts" / "reconcile-postgres-credentials.sh"
    fake_docker = tmp_path / "docker"
    call_log = tmp_path / "docker-calls.log"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "${DOCKER_CALL_LOG:?}"

[[ "${1:-}" == "compose" ]] || exit 1
shift
if [[ "${1:-}" == "version" ]]; then
  exit 0
fi
while [[ "${1:-}" == "-f" || "${1:-}" == "--env-file" ]]; do
  shift 2
done
case "${1:-}" in
  config)
    printf 'postgres\npostgres-credential-reconciler\nbackend\nbackup-worker\n'
    ;;
  run)
    printf '%s\n' \
      'error: credential reconciliation refused because a backup or restore job remains running' \
      >&2
    exit "${RECONCILE_EXIT_CODE:?}"
    ;;
  ps)
    echo "backup-worker-container-id"
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["DOCKER_CALL_LOG"] = str(call_log)
    environment["COMPOSE_FILE"] = "docker-compose.production.yml"
    environment["ENV_FILE"] = ".env.production.example"
    environment["RECONCILE_EXIT_CODE"] = str(reconcile_exit_code)

    result = subprocess.run(
        ["bash", str(script)],
        cwd=dashboard_root,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == reconcile_exit_code
    assert "job remains running" in result.stderr
    calls = call_log.read_text(encoding="utf-8")
    assert "stop backup-worker" in calls
    assert "run --rm --no-deps postgres-credential-reconciler" in calls
    if ambiguous_mutation:
        assert "start backup-worker" not in calls
        assert "up -d --no-deps --force-recreate backend" in calls
        assert "up -d --no-deps --force-recreate backup-worker" in calls
    else:
        assert "start backup-worker" in calls
        assert "force-recreate backend" not in calls
        assert "force-recreate backup-worker" not in calls


class _FakeAsyncConnection:
    def __init__(self, heads: frozenset[str]) -> None:
        self.heads = heads

    async def __aenter__(self) -> "_FakeAsyncConnection":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def run_sync(self, _callback):
        return self.heads


class _FakeAsyncEngine:
    def __init__(self, heads: frozenset[str]) -> None:
        self.heads = heads

    def connect(self) -> _FakeAsyncConnection:
        return _FakeAsyncConnection(self.heads)


def test_backend_exposes_the_shipped_alembic_head() -> None:
    database.expected_alembic_heads.cache_clear()
    assert database.expected_alembic_heads() == frozenset({"20260729_0004"})


@pytest.mark.asyncio
async def test_database_startup_rejects_a_stale_alembic_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        database,
        "engine",
        _FakeAsyncEngine(frozenset({"20260726_0001"})),
    )
    monkeypatch.setattr(
        database,
        "expected_alembic_heads",
        lambda: frozenset({"20260729_0004"}),
    )

    with pytest.raises(RuntimeError, match="current: 20260726_0001"):
        await database.init_db()


@pytest.mark.asyncio
async def test_database_startup_accepts_the_exact_alembic_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = frozenset({"20260729_0004"})
    monkeypatch.setattr(database, "engine", _FakeAsyncEngine(head))
    monkeypatch.setattr(database, "expected_alembic_heads", lambda: head)

    await database.init_db()


def test_production_compose_preserves_postgres_credential_contract() -> None:
    dashboard_root = Path(__file__).resolve().parents[2]
    repository_root = dashboard_root.parent
    development_compose = (dashboard_root / "docker-compose.yml").read_text()
    compose = (dashboard_root / "docker-compose.production.yml").read_text()
    deployment_compose = (
        repository_root / "deploy" / "production" / "docker-compose.production.yml"
    ).read_text()
    backup_script = (
        repository_root / "deploy" / "production" / "backup.sh"
    ).read_text()
    dockerfile = (dashboard_root / "backend" / "Dockerfile").read_text()
    alembic_environment = (
        dashboard_root / "backend" / "alembic" / "env.py"
    ).read_text()
    validation_workflow = (
        repository_root / ".github" / "workflows" / "final-validation.yml"
    ).read_text()
    restore_script = (
        repository_root / "deploy" / "production" / "restore.sh"
    ).read_text()
    reconcile_script = (
        dashboard_root / "scripts" / "reconcile-postgres-credentials.sh"
    ).read_text()
    reconcile_module = (
        dashboard_root / "backend" / "app" / "db" / "postgres_credentials.py"
    ).read_text()
    nginx_config = (dashboard_root / "docker" / "nginx.conf").read_text()
    dashboard_postgres = compose.split("\n  postgres:", 1)[1].split("\n  redis:", 1)[0]
    deployment_postgres = deployment_compose.split("\n  postgres:", 1)[1].split(
        "\n  redis:", 1
    )[0]
    dashboard_backend = compose.split("\n  backend:", 1)[1].split(
        "\n  postgres-credential-reconciler:", 1
    )[0]
    dashboard_reconciler = compose.split("\n  postgres-credential-reconciler:", 1)[
        1
    ].split("\n  backup-worker:", 1)[0]
    dashboard_worker = compose.split("\n  backup-worker:", 1)[1].split(
        "\n  postgres:", 1
    )[0]
    deployment_backend = deployment_compose.split("\n  backend:", 1)[1].split(
        "\n  postgres-credential-reconciler:", 1
    )[0]
    deployment_reconciler = deployment_compose.split(
        "\n  postgres-credential-reconciler:", 1
    )[1].split("\n  backup-worker:", 1)[0]
    deployment_worker = deployment_compose.split("\n  backup-worker:", 1)[1].split(
        "\n  frontend:", 1
    )[0]

    assert 'DATABASE_URL: ""' not in compose
    assert "postgresql+asyncpg://${POSTGRES_USER}" not in compose
    assert "POSTGRES_HOST: postgres" in compose
    assert "pg_isready --host 127.0.0.1 --port 5432 --quiet" in compose
    assert "pg_isready --host 127.0.0.1 --port 5432 --quiet" in development_compose
    assert 'DATABASE_URL: "${DATABASE_URL:-}"' in development_compose
    assert "--host 127.0.0.1" in compose
    assert "http://localhost:8000/ready" in compose
    assert "http://localhost:8000/ready" in dockerfile
    assert "alembic upgrade head" in dockerfile
    assert "python -m app.db.seed" in dockerfile
    assert "render_alembic_config_url(settings.DATABASE_URL)" in alembic_environment
    assert "pg_advisory_xact_lock" in alembic_environment
    assert 'DATABASE_URL: ""' not in deployment_compose
    assert "POSTGRES_HOST: postgres" in deployment_compose
    assert "pg_isready --host 127.0.0.1 --port 5432 --quiet" in deployment_compose
    for backend in (
        dashboard_backend,
        dashboard_worker,
        deployment_backend,
        deployment_worker,
    ):
        assert "DATABASE_URL:" not in backend
        assert "env_file:" in backend
    for backend in (dashboard_backend, deployment_backend):
        assert "service_completed_successfully" in backend
    for worker in (dashboard_worker, deployment_worker):
        assert "condition: service_healthy" in worker
    for reconciler in (dashboard_reconciler, deployment_reconciler):
        assert (
            'command: ["python", "/app/app/db/postgres_credentials.py"]' in reconciler
        )
        assert "- postgres_socket:/var/run/postgresql" in reconciler
        assert "env_file:" in reconciler
    assert (
        'command: ["python", "/app/app/db/postgres_credentials.py"]'
        in development_compose
    )
    assert "env_file:" not in dashboard_postgres
    assert "env_file:" not in deployment_postgres
    assert "- postgres_socket:/var/run/postgresql" in dashboard_postgres
    assert "- postgres_socket:/var/run/postgresql" in deployment_postgres
    for postgres_key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert f"{postgres_key}:" in dashboard_postgres
        assert f"{postgres_key}:" in deployment_postgres
    assert validation_workflow.count("--env-file .env.production") >= 2
    assert (
        'tar -czf "${ARCHIVE_PATH}" -C "${BACKUP_DIR}" "${SQL_NAME}"' in backup_script
    )
    assert 'sha256sum "${ARCHIVE_PATH}"' in backup_script
    assert 'CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"' in backup_script
    assert "pg_dump --clean --if-exists" in backup_script
    assert "umask 077" in backup_script
    assert "deploy/production" not in backup_script
    assert "--set ON_ERROR_STOP=1 --single-transaction" in restore_script
    assert "--owner-backup-id" in restore_script
    assert "FROM backup_records" in restore_script
    assert 'compose cp "backup-worker:${owner_location}"' in restore_script
    assert "Custom backup checksum verification failed." in restore_script
    assert "Custom backup size verification failed." in restore_script
    assert "size_bytes,\n  lease_token,\n  completed_at" in restore_script
    assert (
        ":'backup_size'::bigint,\n  NULL,\n  "
        "to_timestamp(:'backup_completed_epoch'::double precision)"
    ) in restore_script
    assert "lease_token = NULL" in restore_script
    assert "AND lease_token IS NULL" in restore_script
    assert "Legacy backup SHA-256 sidecar is missing or unsafe." in restore_script
    assert "Legacy backup checksum verification failed." in restore_script
    assert "active_recovery_jobs" in restore_script
    assert "'pending'," in restore_script
    assert "'running'" in restore_script
    for recovery_code in (restore_script, reconcile_module):
        assert "to_regclass('backup_records')" in recovery_code
        assert "to_regclass('disaster_recovery_runs')" in recovery_code
        assert "CREATE TEMP TABLE aios_active_recovery_jobs" in recovery_code
        assert "EXECUTE format(" in recovery_code
    assert "run --rm --no-deps postgres-credential-reconciler" in reconcile_script
    assert "service_completed_successfully" in compose
    assert "service_completed_successfully" in deployment_compose
    assert "pg_advisory_xact_lock" in reconcile_module
    assert "LOCK TABLE %s IN ACCESS EXCLUSIVE MODE" in reconcile_module
    assert "ALTER ROLE %I WITH LOGIN PASSWORD %L" in reconcile_module
    assert "VALUES ($1, $2)" in reconcile_module
    assert "password=credentials.password" in reconcile_module
    assert 'fetchval("SELECT 1")' in reconcile_module
    assert "pg_restore --no-password --clean --if-exists" in restore_script
    assert "compose stop backend" in restore_script
    assert "compose stop backup-worker" in restore_script
    assert "backend backup-worker" in restore_script
    for backend in (dashboard_backend, deployment_backend):
        assert "- backup_data:/var/lib/aionex/backups:ro" in backend
    for worker in (dashboard_worker, deployment_worker):
        assert "- backup_data:/var/lib/aionex/backups:rw" in worker
        assert "stop_grace_period: ${BACKUP_JOB_LEASE_SECONDS:-3600}s" in worker
    assert '- "443:443"' not in compose
    assert "server_name _;" in nginx_config
    assert "$aionex_forwarded_proto" in nginx_config


def test_legacy_backup_writes_sha256_sidecar(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    backup_script = repository_root / "deploy" / "production" / "backup.sh"
    env_file = tmp_path / ".env.production"
    compose_file = tmp_path / "docker-compose.production.yml"
    backup_dir = tmp_path / "backups"
    env_file.write_text("POSTGRES_DB=aionex\n", encoding="utf-8")
    compose_file.write_text("services: {}\n", encoding="utf-8")
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\n' 'CREATE TABLE sidecar_test (id integer);'
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["ENV_FILE"] = str(env_file)
    environment["COMPOSE_FILE"] = str(compose_file)
    environment["BACKUP_DIR"] = str(backup_dir)

    result = subprocess.run(
        ["bash", str(backup_script)],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    archives = list(backup_dir.glob("aios-*.tar.gz"))
    assert len(archives) == 1
    archive = archives[0]
    sidecar = Path(f"{archive}.sha256")
    assert sidecar.is_file()
    assert (
        sidecar.read_text(encoding="utf-8").strip()
        == hashlib.sha256(archive.read_bytes()).hexdigest()
    )


def _write_legacy_archive(tmp_path: Path) -> Path:
    sql_file = tmp_path / "aios-test.sql"
    sql_file.write_text("CREATE TABLE restore_test (id integer);\n", encoding="utf-8")
    archive = tmp_path / "aios-test.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(sql_file, arcname=sql_file.name)
    Path(f"{archive}.sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        encoding="utf-8",
    )
    return archive
