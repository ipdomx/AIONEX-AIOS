from pathlib import Path
import subprocess

from sqlalchemy.engine import make_url

from app.core.config import Settings


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


def test_postgres_recovery_script_has_valid_bash_syntax() -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "reconcile-postgres-credentials.sh"
    )
    subprocess.run(["bash", "-n", str(script)], check=True)
