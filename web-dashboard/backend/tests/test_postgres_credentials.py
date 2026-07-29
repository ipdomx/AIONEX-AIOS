import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy.engine import URL

from app.db import postgres_credentials
from app.db.postgres_credentials import (
    BundledPostgresCredentials,
    CredentialConfigurationError,
    reconcile_bundled_postgres_credentials,
    resolve_bundled_credentials,
)


def _postgres_environment(**overrides: str) -> dict[str, str]:
    environment = {
        "DATABASE_URL": "",
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USER": "aionex",
        "POSTGRES_PASSWORD": "safe-password",
        "POSTGRES_DB": "aionex",
    }
    environment.update(overrides)
    return environment


def test_postgres_values_are_the_default_credential_source() -> None:
    credentials = resolve_bundled_credentials(_postgres_environment())

    assert credentials == BundledPostgresCredentials(
        host="postgres",
        port=5432,
        user="aionex",
        password="safe-password",
        database="aionex",
    )


def test_legacy_database_url_password_takes_precedence() -> None:
    password = "p@ss:/with%#'\"$\\ space"
    database_url = URL.create(
        "postgresql+asyncpg",
        username='legacy"user',
        password=password,
        host="postgres",
        port=5432,
        database="legacy database",
    ).render_as_string(hide_password=False)
    environment = _postgres_environment(
        DATABASE_URL=database_url,
        POSTGRES_USER='legacy"user',
        POSTGRES_PASSWORD="conflicting-password",
        POSTGRES_DB="legacy database",
    )

    credentials = resolve_bundled_credentials(environment)

    assert credentials is not None
    assert credentials.user == 'legacy"user'
    assert credentials.password == password
    assert credentials.database == "legacy database"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("POSTGRES_HOST", ""),
        ("POSTGRES_HOST", "database"),
        ("POSTGRES_PORT", ""),
        ("POSTGRES_PORT", "not-a-port"),
        ("POSTGRES_PORT", "18446744073709557048"),
        ("POSTGRES_USER", ""),
        ("POSTGRES_PASSWORD", ""),
        ("POSTGRES_DB", ""),
    ],
)
def test_incomplete_or_non_bundled_postgres_values_are_rejected(
    key: str,
    value: str,
) -> None:
    with pytest.raises(CredentialConfigurationError):
        resolve_bundled_credentials(_postgres_environment(**{key: value}))


@pytest.mark.parametrize(
    "database_url",
    [
        "postgres://aionex:safe-password@postgres:5432/aionex",
        "postgresql://aionex:safe-password@postgres:5432/aionex",
        "postgresql+psycopg2://aionex:safe-password@postgres:5432/aionex",
        "postgresql+evil://aionex:safe-password@postgres:5432/aionex",
        "PostgreSQL+AsyncPG://aionex:safe-password@postgres:5432/aionex",
        "postgresql+asyncpg://aionex:safe-password@postgres:0/aionex",
        "postgresql+asyncpg://aionex:safe-password@postgres:5433/aionex",
        "postgresql+asyncpg://aionex:safe-password@postgres:"
        "18446744073709557048/aionex",
        "postgresql+asyncpg://aionex:@postgres:5432/aionex",
        "postgresql+asyncpg://aionex:safe-password@postgres:5432/aionex?ssl=false",
        "postgresql+asyncpg://aionex:safe-password@postgres:5432/aionex"
        "?host=external",
        "postgresql+asyncpg://aionex:safe-password@postgres:5432/aionex" "?p%6frt=5433",
    ],
)
def test_unsafe_database_url_forms_are_rejected(database_url: str) -> None:
    with pytest.raises(CredentialConfigurationError):
        resolve_bundled_credentials(_postgres_environment(DATABASE_URL=database_url))


def test_external_database_url_skips_bundled_reconciliation() -> None:
    environment = _postgres_environment(
        DATABASE_URL=(
            "postgresql+asyncpg://external:secret" "@db.example.test:6432/external"
        ),
    )

    assert resolve_bundled_credentials(environment) is None


def test_database_url_password_override_does_not_leak() -> None:
    secret = "do-not-print-this-password"
    database_url = "postgresql+asyncpg://aionex:" f"{secret}@postgres:5432/aionex"
    environment = _postgres_environment(
        DATABASE_URL=database_url,
        POSTGRES_PASSWORD="other",
    )

    credentials = resolve_bundled_credentials(environment)

    assert credentials is not None
    assert credentials.user == "aionex"
    assert credentials.password == secret
    assert credentials.database == "aionex"
    assert secret not in repr(credentials)
    assert database_url not in repr(credentials)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("POSTGRES_USER", "stale_user"),
        ("POSTGRES_DB", "stale_database"),
    ],
)
def test_bundled_database_url_identity_conflicts_fail_closed(
    key: str,
    value: str,
) -> None:
    secret = "do-not-print-this-password"
    overrides = {
        "DATABASE_URL": (
            "postgresql+asyncpg://legacy_user:"
            f"{secret}@postgres:5432/legacy_database"
        ),
        "POSTGRES_USER": "legacy_user",
        "POSTGRES_DB": "legacy_database",
    }
    overrides[key] = value
    environment = _postgres_environment(**overrides)

    with pytest.raises(CredentialConfigurationError) as exc_info:
        resolve_bundled_credentials(environment)

    assert secret not in str(exc_info.value)


@pytest.mark.parametrize("value", ["", "119", "604801", "not-a-number"])
def test_invalid_recovery_lease_is_rejected(value: str) -> None:
    with pytest.raises(CredentialConfigurationError):
        postgres_credentials._resolve_recovery_lease_seconds(
            {"BACKUP_JOB_LEASE_SECONDS": value}
        )


def test_default_recovery_lease_matches_worker_default() -> None:
    assert postgres_credentials._resolve_recovery_lease_seconds({}) == 3600


def test_standalone_reconciler_does_not_load_application_settings() -> None:
    script = Path(postgres_credentials.__file__).resolve()
    environment = os.environ.copy()
    environment.pop("SECRET_KEY", None)
    environment.update(
        _postgres_environment(
            DATABASE_URL=(
                "postgresql+asyncpg://external:secret" "@db.example.test:6432/external"
            )
        )
    )

    result = subprocess.run(
        [sys.executable, str(script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "External DATABASE_URL detected" in result.stdout
    assert "SECRET_KEY" not in result.stderr


class _FakeTransaction:
    async def __aenter__(self) -> "_FakeTransaction":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeConnection:
    def __init__(
        self,
        *,
        active_jobs: int = 0,
        authenticated: bool = False,
        execute_error: Exception | None = None,
        fail_when: str = "",
    ) -> None:
        self.active_jobs = active_jobs
        self.authenticated = authenticated
        self.execute_error = execute_error
        self.fail_when = fail_when
        self.closed = False
        self.executions: list[str] = []
        self.execution_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetches: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def execute(self, statement: str, *args: object) -> str:
        self.executions.append(statement)
        self.execution_calls.append((statement, args))
        if self.execute_error is not None and self.fail_when in statement:
            raise self.execute_error
        return "OK"

    async def fetchval(self, statement: str, *args: object) -> object:
        self.fetches.append((statement, args))
        if statement == "SELECT job_count FROM aios_active_recovery_jobs":
            return self.active_jobs
        if statement == "SELECT 1" and self.authenticated:
            return 1
        raise AssertionError(f"unexpected query: {statement}")

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def credentials() -> BundledPostgresCredentials:
    return BundledPostgresCredentials(
        host="postgres",
        port=5432,
        user="aionex",
        password="safe-password",
        database="aionex",
    )


def test_password_verifier_uses_local_socket_without_plaintext_connection_password(
    monkeypatch: pytest.MonkeyPatch,
    credentials: BundledPostgresCredentials,
) -> None:
    class FakeVerifierConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    connection = FakeVerifierConnection()
    connect_calls: list[dict[str, object]] = []
    encrypt_calls: list[tuple[str, str, object]] = []

    def fake_connect(**kwargs: object) -> FakeVerifierConnection:
        connect_calls.append(kwargs)
        return connection

    def fake_encrypt(password: str, user: str, *, scope: object) -> str:
        encrypt_calls.append((password, user, scope))
        return "SCRAM-SHA-256$4096:test-verifier"

    monkeypatch.setattr(postgres_credentials.psycopg2, "connect", fake_connect)
    monkeypatch.setattr(postgres_credentials, "encrypt_password", fake_encrypt)

    verifier = postgres_credentials._build_password_verifier(
        credentials,
        "/var/run/postgresql",
    )

    assert verifier == "SCRAM-SHA-256$4096:test-verifier"
    assert connect_calls == [
        {
            "host": "/var/run/postgresql",
            "user": "aionex",
            "dbname": "aionex",
            "connect_timeout": 15,
        }
    ]
    assert encrypt_calls == [("safe-password", "aionex", connection)]
    assert "safe-password" not in repr(credentials)
    assert connection.closed


@pytest.mark.asyncio
async def test_reconcile_uses_local_trust_then_authenticated_tcp(
    monkeypatch: pytest.MonkeyPatch,
    credentials: BundledPostgresCredentials,
) -> None:
    local_connection = _FakeConnection()
    authenticated_connection = _FakeConnection(authenticated=True)
    connections: list[dict[str, object]] = []

    async def fake_connect(**kwargs: object) -> _FakeConnection:
        connections.append(kwargs)
        if len(connections) == 1:
            raise postgres_credentials.asyncpg.InvalidPasswordError(
                "password authentication failed"
            )
        if len(connections) == 2:
            return local_connection
        return authenticated_connection

    monkeypatch.setattr(postgres_credentials.asyncpg, "connect", fake_connect)
    password_verifier = "SCRAM-SHA-256$4096:test-verifier"
    monkeypatch.setattr(
        postgres_credentials,
        "_build_password_verifier",
        lambda *_args: password_verifier,
    )

    await reconcile_bundled_postgres_credentials(
        credentials,
        socket_directory="/var/run/postgresql",
    )

    expected_password_connection = {
        "host": "postgres",
        "port": 5432,
        "user": "aionex",
        "password": "safe-password",
        "database": "aionex",
        "timeout": 15,
    }
    assert connections[0] == expected_password_connection
    assert connections[1] == {
        "host": "/var/run/postgresql",
        "user": "aionex",
        "database": "aionex",
        "timeout": 15,
    }
    assert connections[2] == expected_password_connection
    credential_insert = next(
        item
        for item in local_connection.execution_calls
        if item[0].startswith("INSERT INTO aios_postgres_credentials")
    )
    assert credential_insert[1] == ("aionex", password_verifier)
    assert "safe-password" not in credential_insert[0]
    assert not any(
        "safe-password" in statement for statement in local_connection.executions
    )
    recovery_query = next(
        statement
        for statement in local_connection.executions
        if "DO $aionex$" in statement
    )
    assert recovery_query.count("LOCK TABLE %s IN ACCESS EXCLUSIVE MODE") == 2
    assert recovery_query.count("updated_at >= $2") == 2
    assert "secs => lease_seconds::double precision" in recovery_query
    assert (
        "SET LOCAL lock_timeout = '30s'",
        (),
    ) in local_connection.execution_calls
    assert (
        "SET LOCAL statement_timeout = '90s'",
        (),
    ) in local_connection.execution_calls


@pytest.mark.asyncio
async def test_reconcile_returns_when_password_already_matches(
    monkeypatch: pytest.MonkeyPatch,
    credentials: BundledPostgresCredentials,
) -> None:
    authenticated_connection = _FakeConnection(authenticated=True)

    async def fake_connect(**_kwargs: object) -> _FakeConnection:
        return authenticated_connection

    monkeypatch.setattr(postgres_credentials.asyncpg, "connect", fake_connect)

    await reconcile_bundled_postgres_credentials(
        credentials,
        socket_directory="/var/run/postgresql",
    )

    assert authenticated_connection.closed


@pytest.mark.asyncio
async def test_reconcile_rejects_active_recovery_jobs(
    monkeypatch: pytest.MonkeyPatch,
    credentials: BundledPostgresCredentials,
) -> None:
    local_connection = _FakeConnection(active_jobs=1)
    connection_count = 0

    async def fake_connect(**_kwargs: object) -> _FakeConnection:
        nonlocal connection_count
        connection_count += 1
        if connection_count == 1:
            raise postgres_credentials.asyncpg.InvalidPasswordError(
                "password authentication failed"
            )
        return local_connection

    monkeypatch.setattr(postgres_credentials.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(
        postgres_credentials,
        "_build_password_verifier",
        lambda *_args: "SCRAM-SHA-256$4096:test-verifier",
    )

    with pytest.raises(CredentialConfigurationError, match="job remains running"):
        await reconcile_bundled_postgres_credentials(
            credentials,
            socket_directory="/var/run/postgresql",
        )

    assert connection_count == 2
    assert not any(
        statement.startswith('ALTER ROLE "')
        for statement in local_connection.executions
    )
    assert local_connection.closed


def test_unexpected_runtime_errors_do_not_print_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "runtime-secret-that-must-not-leak"

    async def fail() -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(postgres_credentials, "_run", fail)

    assert postgres_credentials.main() == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert "RuntimeError" in captured.err


@pytest.mark.parametrize(
    "error",
    [
        postgres_credentials.asyncpg.LockNotAvailableError("lock timeout"),
        postgres_credentials.asyncpg.QueryCanceledError("statement timeout"),
    ],
)
@pytest.mark.asyncio
async def test_transaction_timeouts_fail_cleanly_before_password_change(
    monkeypatch: pytest.MonkeyPatch,
    credentials: BundledPostgresCredentials,
    error: Exception,
) -> None:
    local_connection = _FakeConnection(
        execute_error=error,
        fail_when="pg_advisory_xact_lock",
    )
    connection_count = 0

    async def fake_connect(**_kwargs: object) -> _FakeConnection:
        nonlocal connection_count
        connection_count += 1
        if connection_count == 1:
            raise postgres_credentials.asyncpg.InvalidPasswordError(
                "password authentication failed"
            )
        return local_connection

    monkeypatch.setattr(postgres_credentials.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(
        postgres_credentials,
        "_build_password_verifier",
        lambda *_args: "SCRAM-SHA-256$4096:test-verifier",
    )

    with pytest.raises(
        CredentialConfigurationError,
        match="no credential change was committed",
    ):
        await reconcile_bundled_postgres_credentials(
            credentials,
            socket_directory="/var/run/postgresql",
        )

    assert not any(
        "ALTER ROLE" in statement for statement in local_connection.executions
    )
    assert local_connection.closed


def test_post_commit_query_cancellation_fails_closed_without_secret_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail() -> None:
        raise postgres_credentials.asyncpg.QueryCanceledError("statement timeout")

    monkeypatch.setattr(postgres_credentials, "_run", fail)

    assert postgres_credentials.main() == 1
    captured = capsys.readouterr()
    assert "QueryCanceledError" in captured.err
    assert "statement timeout" not in captured.err
    assert "may already have been synchronized" not in captured.err


def test_external_database_skip_is_reported_without_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def skip() -> bool:
        return False

    monkeypatch.setattr(postgres_credentials, "_run", skip)

    assert postgres_credentials.main() == 0
    captured = capsys.readouterr()
    assert "External DATABASE_URL detected" in captured.out
