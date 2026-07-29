"""Safe PostgreSQL credential reconciliation for bundled Compose deployments."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
import sys
from typing import Mapping

import asyncpg
import psycopg2
from psycopg2.extensions import encrypt_password
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class CredentialConfigurationError(RuntimeError):
    """Raised when database credential sources are unsafe or inconsistent."""


@dataclass(frozen=True)
class BundledPostgresCredentials:
    """One canonical credential set for the bundled PostgreSQL service."""

    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str


def resolve_bundled_credentials(
    environ: Mapping[str, str],
) -> BundledPostgresCredentials | None:
    """Resolve the credentials used by the bundled PostgreSQL service.

    Existing deployments may still carry a DATABASE_URL whose password differs
    from POSTGRES_* because those initialization values do not update an
    existing PostgreSQL volume. For a URL targeting the bundled ``postgres``
    service, the URL password is therefore authoritative while its user and
    database must match POSTGRES_*. A valid external URL is deliberately
    skipped so this helper never mutates the bundled database on behalf of an
    external-database deployment.
    """

    host = environ.get("POSTGRES_HOST", "").strip()
    port_value = environ.get("POSTGRES_PORT", "").strip()
    user = environ.get("POSTGRES_USER", "")
    password = environ.get("POSTGRES_PASSWORD", "")
    database = environ.get("POSTGRES_DB", "")

    database_url = environ.get("DATABASE_URL", "").strip()
    url_password: str | None = None
    if database_url:
        try:
            url = make_url(database_url)
            url_port = url.port if url.port is not None else 5432
        except (ArgumentError, ValueError) as exc:
            raise CredentialConfigurationError(
                "DATABASE_URL is not a valid PostgreSQL URL"
            ) from exc

        if url.drivername != "postgresql+asyncpg":
            raise CredentialConfigurationError(
                "DATABASE_URL must use the postgresql+asyncpg driver"
            )
        if not url.host:
            raise CredentialConfigurationError(
                "DATABASE_URL must include a database host"
            )
        url_password = url.password
        if not url.username or not url_password or not url.database:
            raise CredentialConfigurationError(
                "DATABASE_URL must include username, password, and database"
            )
        if url.host.lower() != "postgres":
            return None
        if url_port != 5432:
            raise CredentialConfigurationError(
                "Bundled DATABASE_URL must use the postgres service on port 5432"
            )
        if url.query:
            raise CredentialConfigurationError(
                "Bundled DATABASE_URL query parameters are not supported"
            )

    if not all((host, port_value, user, password, database)):
        raise CredentialConfigurationError(
            "POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, "
            "and POSTGRES_DB are required"
        )
    if host.lower() != "postgres":
        raise CredentialConfigurationError(
            "POSTGRES_HOST must target the bundled postgres service"
        )
    try:
        port = int(port_value, 10)
    except ValueError as exc:
        raise CredentialConfigurationError("POSTGRES_PORT must be 5432") from exc
    if port != 5432:
        raise CredentialConfigurationError("POSTGRES_PORT must be 5432")

    if database_url:
        assert url_password is not None
        assert url.username is not None
        assert url.database is not None
        if url.username != user or url.database != database:
            raise CredentialConfigurationError(
                "Bundled DATABASE_URL user and database must match POSTGRES_*"
            )
        password = url_password

    return BundledPostgresCredentials(
        host="postgres",
        port=5432,
        user=user,
        password=password,
        database=database,
    )


def _build_password_verifier(
    credentials: BundledPostgresCredentials,
    socket_directory: str,
) -> str:
    """Build the server-selected password verifier without logging plaintext."""

    connection = psycopg2.connect(
        host=socket_directory,
        user=credentials.user,
        dbname=credentials.database,
        connect_timeout=15,
    )
    try:
        return encrypt_password(
            credentials.password,
            credentials.user,
            scope=connection,
        )
    finally:
        connection.close()


def _resolve_recovery_lease_seconds(environ: Mapping[str, str]) -> int:
    raw_value = environ.get("BACKUP_JOB_LEASE_SECONDS", "3600").strip()
    try:
        lease_seconds = int(raw_value, 10)
    except ValueError as exc:
        raise CredentialConfigurationError(
            "BACKUP_JOB_LEASE_SECONDS must be an integer from 120 to 604800"
        ) from exc
    if not 120 <= lease_seconds <= 604800:
        raise CredentialConfigurationError(
            "BACKUP_JOB_LEASE_SECONDS must be an integer from 120 to 604800"
        )
    return lease_seconds


async def _active_recovery_job_count(
    connection: asyncpg.Connection,
    lease_seconds: int,
) -> int:
    await connection.execute(
        "CREATE TEMP TABLE aios_recovery_policy "
        "(lease_seconds bigint NOT NULL) ON COMMIT DROP"
    )
    await connection.execute(
        "INSERT INTO aios_recovery_policy (lease_seconds) VALUES ($1)",
        lease_seconds,
    )
    await connection.execute(
        "CREATE TEMP TABLE aios_active_recovery_jobs "
        "(job_count bigint NOT NULL) ON COMMIT DROP"
    )
    await connection.execute("""
        DO $aionex$
        DECLARE
          relation regclass;
          relation_count bigint;
          total bigint := 0;
          lease_seconds bigint;
          stale_before timestamptz;
        BEGIN
          SELECT policy.lease_seconds
          INTO STRICT lease_seconds
          FROM aios_recovery_policy AS policy;
          stale_before := clock_timestamp() - make_interval(
            secs => lease_seconds::double precision
          );

          relation := to_regclass('backup_records');
          IF relation IS NOT NULL THEN
            EXECUTE format(
              'LOCK TABLE %s IN ACCESS EXCLUSIVE MODE',
              relation
            );
            EXECUTE format(
              'SELECT count(*) FROM %s '
              'WHERE status = $1 AND updated_at >= $2',
              relation
            ) INTO relation_count USING 'running', stale_before;
            total := total + relation_count;
          END IF;

          relation := to_regclass('disaster_recovery_runs');
          IF relation IS NOT NULL THEN
            EXECUTE format(
              'LOCK TABLE %s IN ACCESS EXCLUSIVE MODE',
              relation
            );
            EXECUTE format(
              'SELECT count(*) FROM %s '
              'WHERE status = $1 AND updated_at >= $2',
              relation
            ) INTO relation_count USING 'running', stale_before;
            total := total + relation_count;
          END IF;

          INSERT INTO aios_active_recovery_jobs (job_count) VALUES (total);
        END;
        $aionex$;
        """)
    return int(
        await connection.fetchval("SELECT job_count FROM aios_active_recovery_jobs")
    )


async def _password_authentication_succeeds(
    credentials: BundledPostgresCredentials,
) -> bool:
    try:
        connection = await asyncpg.connect(
            host=credentials.host,
            port=credentials.port,
            user=credentials.user,
            password=credentials.password,
            database=credentials.database,
            timeout=15,
        )
    except asyncpg.InvalidPasswordError:
        return False

    try:
        return await connection.fetchval("SELECT 1") == 1
    finally:
        await connection.close()


async def reconcile_bundled_postgres_credentials(
    credentials: BundledPostgresCredentials,
    *,
    socket_directory: str,
    recovery_lease_seconds: int = 3600,
) -> None:
    """Synchronize one existing role, then verify password-authenticated TCP."""

    if await _password_authentication_succeeds(credentials):
        return

    password_verifier = await asyncio.to_thread(
        _build_password_verifier,
        credentials,
        socket_directory,
    )
    local_connection = await asyncpg.connect(
        host=socket_directory,
        user=credentials.user,
        database=credentials.database,
        timeout=15,
    )
    try:
        try:
            async with local_connection.transaction():
                await local_connection.execute("SET LOCAL lock_timeout = '30s'")
                await local_connection.execute("SET LOCAL statement_timeout = '90s'")
                await local_connection.execute(
                    "SELECT pg_advisory_xact_lock(741905231017001)"
                )
                if await _active_recovery_job_count(
                    local_connection,
                    recovery_lease_seconds,
                ):
                    raise CredentialConfigurationError(
                        "credential reconciliation refused because a backup or "
                        "restore job remains running"
                    )
                await local_connection.execute(
                    "CREATE TEMP TABLE aios_postgres_credentials ("
                    "role_name text NOT NULL, "
                    "password_verifier text NOT NULL"
                    ") ON COMMIT DROP"
                )
                await local_connection.execute(
                    "INSERT INTO aios_postgres_credentials "
                    "(role_name, password_verifier) VALUES ($1, $2)",
                    credentials.user,
                    password_verifier,
                )
                await local_connection.execute("""
                    DO $aionex$
                    DECLARE
                      target_role text;
                      target_verifier text;
                    BEGIN
                      SELECT role_name, password_verifier
                      INTO STRICT target_role, target_verifier
                      FROM aios_postgres_credentials;
                      EXECUTE format(
                        'ALTER ROLE %I WITH LOGIN PASSWORD %L',
                        target_role,
                        target_verifier
                      );
                    END;
                    $aionex$;
                    """)
        except (asyncpg.LockNotAvailableError, asyncpg.QueryCanceledError) as exc:
            raise CredentialConfigurationError(
                "PostgreSQL credential reconciliation timed out while waiting "
                "for database activity; no credential change was committed"
            ) from exc
    finally:
        await local_connection.close()

    if not await _password_authentication_succeeds(credentials):
        raise RuntimeError("PostgreSQL authentication probe failed")


async def _run() -> bool:
    credentials = resolve_bundled_credentials(os.environ)
    if credentials is None:
        return False
    socket_directory = os.environ.get(
        "POSTGRES_SOCKET_DIR",
        "/var/run/postgresql",
    )
    if not socket_directory.startswith("/"):
        raise CredentialConfigurationError(
            "POSTGRES_SOCKET_DIR must be an absolute path"
        )
    await reconcile_bundled_postgres_credentials(
        credentials,
        socket_directory=socket_directory,
        recovery_lease_seconds=_resolve_recovery_lease_seconds(os.environ),
    )
    return True


def main() -> int:
    """Run reconciliation without printing credentials or connection URLs."""

    try:
        reconciled = asyncio.run(_run())
    except CredentialConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "error: PostgreSQL credential reconciliation failed; "
            "the configured role may already have been synchronized",
            file=sys.stderr,
        )
        return 2
    if not reconciled:
        print("External DATABASE_URL detected; bundled reconciliation skipped.")
        return 0
    print("Bundled PostgreSQL credentials verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
