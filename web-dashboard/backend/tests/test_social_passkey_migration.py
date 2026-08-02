import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base
from app.db import models


def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260802_0005_social_identity_passkeys.py"
    )
    spec = importlib.util.spec_from_file_location(
        "social_identity_passkeys_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(connection: sa.Connection) -> None:
    migration = _load_migration_module()
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


def _assert_auth_schema(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    assert {"external_identities", "passkey_credentials"}.issubset(
        inspector.get_table_names()
    )
    assert {
        "ix_external_identities_user_id",
        "ix_external_identity_user_provider",
    }.issubset(
        {index["name"] for index in inspector.get_indexes("external_identities")}
    )
    assert {
        "ix_passkey_credentials_user_id",
        "ix_passkey_user_created",
    }.issubset(
        {index["name"] for index in inspector.get_indexes("passkey_credentials")}
    )


def test_upgrade_accepts_tables_already_created_by_initial_metadata() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)

        _run_upgrade(connection)
        _assert_auth_schema(connection)


def test_upgrade_creates_missing_tables_and_is_repeatable() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        models.PasskeyCredential.__table__.drop(connection)
        models.ExternalIdentity.__table__.drop(connection)

        _run_upgrade(connection)
        _run_upgrade(connection)
        _assert_auth_schema(connection)
