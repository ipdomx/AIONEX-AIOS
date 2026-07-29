import hashlib
import os
from pathlib import Path
import subprocess

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
printf '%s\\n' "$*" >> "${DOCKER_CALL_LOG:?}"

if [[ "${1:-}" == "inspect" ]]; then
  if [[ "$*" == *"backup-worker-container-id"* ]]; then
    echo healthy
  else
    echo healthy
  fi
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
    printf 'postgres\\nbackend\\n'
    if [[ "${HAS_BACKUP_WORKER:-false}" == "true" ]]; then
      printf 'backup-worker\\n'
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

    expected_call_count = 10 if compose_file else 8
    assert len(wrapped_calls) == expected_call_count
    assert all(line.startswith(expected_prefix) for line in wrapped_calls)
    assert any(line.endswith("config --services") for line in wrapped_calls)
    assert any(line.endswith("config --environment") for line in wrapped_calls)
    assert any(line.endswith("up -d --no-deps postgres") for line in wrapped_calls)
    assert any(
        line.endswith("up -d --force-recreate backend") for line in wrapped_calls
    )
    assert any(line.endswith("ps -q backend") for line in wrapped_calls)
    if compose_file:
        assert any(
            line.endswith("up -d --no-deps --force-recreate backup-worker")
            for line in wrapped_calls
        )
        assert any(line.endswith("ps -q backup-worker") for line in wrapped_calls)
    else:
        assert not any("backup-worker" in line for line in wrapped_calls)


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
    assert database.expected_alembic_heads() == frozenset({"20260729_0003"})


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
        lambda: frozenset({"20260729_0003"}),
    )

    with pytest.raises(RuntimeError, match="current: 20260726_0001"):
        await database.init_db()


@pytest.mark.asyncio
async def test_database_startup_accepts_the_exact_alembic_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = frozenset({"20260729_0003"})
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
    nginx_config = (dashboard_root / "docker" / "nginx.conf").read_text()
    dashboard_postgres = compose.split("\n  postgres:", 1)[1].split("\n  redis:", 1)[0]
    deployment_postgres = deployment_compose.split("\n  postgres:", 1)[1].split(
        "\n  redis:", 1
    )[0]

    assert 'DATABASE_URL: ""' in compose
    assert "postgresql+asyncpg://${POSTGRES_USER}" not in compose
    assert "POSTGRES_HOST: postgres" in compose
    assert 'PGPASSWORD="$${POSTGRES_PASSWORD}"' in compose
    assert 'PGPASSWORD="$${POSTGRES_PASSWORD}"' in development_compose
    assert "--host 127.0.0.1" in compose
    assert "http://localhost:8000/ready" in compose
    assert "http://localhost:8000/ready" in dockerfile
    assert "alembic upgrade head" in dockerfile
    assert "python -m app.db.seed" in dockerfile
    assert "render_alembic_config_url(settings.DATABASE_URL)" in alembic_environment
    assert "pg_advisory_xact_lock" in alembic_environment
    assert 'DATABASE_URL: ""' in deployment_compose
    assert "POSTGRES_HOST: postgres" in deployment_compose
    assert 'PGPASSWORD="$${POSTGRES_PASSWORD}"' in deployment_compose
    assert "env_file:" not in dashboard_postgres
    assert "env_file:" not in deployment_postgres
    for postgres_key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert f"{postgres_key}:" in dashboard_postgres
        assert f"{postgres_key}:" in deployment_postgres
    assert validation_workflow.count("--env-file .env.production") >= 2
    assert (
        'tar -czf "${ARCHIVE_PATH}" -C "${BACKUP_DIR}" "${SQL_NAME}"' in backup_script
    )
    assert "pg_dump --clean --if-exists" in backup_script
    assert "umask 077" in backup_script
    assert "deploy/production" not in backup_script
    assert "--set ON_ERROR_STOP=1 --single-transaction" in restore_script
    assert "--owner-backup-id" in restore_script
    assert "FROM backup_records" in restore_script
    assert 'compose cp "backup-worker:${owner_location}"' in restore_script
    assert "Custom backup checksum verification failed." in restore_script
    assert "Custom backup size verification failed." in restore_script
    assert "pg_restore --no-password --clean --if-exists" in restore_script
    assert "compose stop backend" in restore_script
    assert "compose stop backup-worker" in restore_script
    assert "backend backup-worker" in restore_script
    assert '- "443:443"' not in compose
    assert "server_name _;" in nginx_config
    assert "$aionex_forwarded_proto" in nginx_config


def test_owner_backup_restore_runbook_verifies_and_restores_custom_archive(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    restore_script = repository_root / "deploy" / "production" / "restore.sh"
    compose_file = (
        repository_root / "deploy" / "production" / "docker-compose.production.yml"
    )
    env_file = tmp_path / ".env.production"
    env_file.write_text("POSTGRES_DB=aionex\n", encoding="utf-8")
    payload = b"PGDMPowner-backup-runbook-test"
    checksum = hashlib.sha256(payload).hexdigest()
    fake_docker = tmp_path / "docker"
    call_log = tmp_path / "docker-calls.log"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "${DOCKER_CALL_LOG:?}"
[[ "${1:-}" == "compose" ]] || exit 1
shift
while [[ "${1:-}" == "-f" || "${1:-}" == "--env-file" ]]; do
  shift 2
done
command="${1:-}"
shift || true
case "$command" in
  ps)
    echo "${*: -1}-container-id"
    ;;
  cp)
    destination="${*: -1}"
    printf 'PGDMPowner-backup-runbook-test' > "$destination"
    ;;
  exec)
    if [[ "$*" == *"AIOS_BACKUP_REPAIR=1"* ]]; then
      cat >> "${DOCKER_CALL_LOG:?}"
    elif [[ "$*" == *"AIOS_BACKUP_ID="* ]]; then
      printf '%s\\t%s\\t/var/lib/aionex/backups/backup-aaaaaaaaaaaaaaaaaaaaaaaa.dump\\t%s\\t%s\\t%s\\n' \
        "6461746162617365" "706c6174666f726d" \
        "${FAKE_CHECKSUM:?}" "${FAKE_SIZE:?}" "1785283200.123456"
    else
      cat >/dev/null
    fi
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["DOCKER_CALL_LOG"] = str(call_log)
    environment["FAKE_CHECKSUM"] = checksum
    environment["FAKE_SIZE"] = str(len(payload))
    environment["TMPDIR"] = str(tmp_path)
    environment["ENV_FILE"] = str(env_file)
    environment["COMPOSE_FILE"] = str(compose_file)

    result = subprocess.run(
        [
            "bash",
            str(restore_script),
            "--owner-backup-id",
            "12345678-1234-4123-8123-123456789abc",
        ],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text(encoding="utf-8")
    assert (
        "cp backup-worker:/var/lib/aionex/backups/"
        "backup-aaaaaaaaaaaaaaaaaaaaaaaa.dump" in calls
    )
    assert "stop backup-worker" in calls
    assert "stop backend" in calls
    assert "pg_restore --no-password --clean --if-exists" in calls
    assert "AIOS_BACKUP_REPAIR=1" in calls
    assert "INSERT INTO backup_records" in calls
    assert "ON CONFLICT (id) DO UPDATE" in calls
    assert "status = EXCLUDED.status" in calls
    assert "completed_at = EXCLUDED.completed_at" in calls
    assert "up -d --wait --wait-timeout 180 backend backup-worker" in calls


def test_legacy_production_environment_matches_backend_and_proxy_contracts() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    example = (
        repository_root / "deploy" / "production" / ".env.production.example"
    ).read_text()

    for key in (
        "PUBLIC_DOMAIN",
        "API_DOMAIN",
        "PUBLIC_ORIGIN",
        "API_ORIGIN",
        "CORS_ORIGINS",
        "POSTGRES_PASSWORD",
        "SECRET_KEY",
        "AIOS_BOOTSTRAP_OWNER_PASSWORD",
        "GOOGLE_API_KEY",
        "SMTP_USER",
    ):
        assert f"{key}=" in example

    assert "ALLOWED_ORIGINS=" not in example
    assert "GEMINI_API_KEY=" not in example
    assert "SMTP_USERNAME=" not in example


@pytest.mark.parametrize(
    "script_name",
    ["validate-production.sh", "final-release-check.sh"],
)
def test_legacy_production_validation_enforces_domain_contract(
    tmp_path: Path,
    script_name: str,
) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    fake_docker = tmp_path / "docker"
    fake_docker.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    env_file = tmp_path / ".env.production"
    env_file.write_text(
        "\n".join(
            (
                "PUBLIC_DOMAIN=app.example.test",
                "API_DOMAIN=api.example.test",
                "PUBLIC_ORIGIN=https://app.example.test",
                "API_ORIGIN=https://api.example.test",
                'CORS_ORIGINS=["https://app.example.test"]',
                "POSTGRES_DB=aionex",
                "POSTGRES_USER=aionex",
                "POSTGRES_PASSWORD=not-a-placeholder",
                f"SECRET_KEY={'s' * 32}",
                "AIOS_BOOTSTRAP_OWNER_PASSWORD=strong-owner-password",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"
    environment["ENV_FILE"] = str(env_file)

    valid_result = subprocess.run(
        ["bash", str(repository_root / "deploy" / "production" / script_name)],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert valid_result.returncode == 0, valid_result.stderr

    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace(
            "PUBLIC_ORIGIN=https://app.example.test",
            "PUBLIC_ORIGIN=https://wrong.example.test",
        ),
        encoding="utf-8",
    )
    invalid_result = subprocess.run(
        ["bash", str(repository_root / "deploy" / "production" / script_name)],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert invalid_result.returncode != 0
    assert "PUBLIC_ORIGIN must equal https://PUBLIC_DOMAIN" in invalid_result.stderr
