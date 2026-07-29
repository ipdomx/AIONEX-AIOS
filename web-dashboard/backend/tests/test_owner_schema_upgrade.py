"""Database-only coverage for upgrading the deployed Owner schema."""

from __future__ import annotations

import importlib.util
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import InterfaceError, OperationalError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
OWNER_MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260729_0002_owner_control_plane.py"
)
RUNTIME_SAFETY_MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260729_0003_owner_runtime_safety.py"
)


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_owner_migration() -> ModuleType:
    return _load_migration(
        OWNER_MIGRATION_PATH,
        "owner_control_plane_schema_upgrade",
    )


def _load_runtime_safety_migration() -> ModuleType:
    return _load_migration(
        RUNTIME_SAFETY_MIGRATION_PATH,
        "owner_runtime_safety_schema_upgrade",
    )


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def _postgres_test_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("DATABASE_URL is not configured for the PostgreSQL migration test")

    url = sa.engine.make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        pytest.skip("DATABASE_URL does not point to PostgreSQL")

    try:
        return sa.create_engine(url.set(drivername="postgresql+psycopg2"))
    except ModuleNotFoundError:
        pytest.skip("psycopg2 is not installed for the PostgreSQL migration test")


def _legacy_metadata() -> sa.MetaData:
    """Represent the deployed 60ff89a tables touched by revision 0002."""
    metadata = sa.MetaData()
    organizations = sa.Table(
        "organizations",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
    )
    roles = sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey(organizations.c.id, ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
    )
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey(organizations.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.String(length=36),
            sa.ForeignKey(roles.c.id, ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
    )
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey(organizations.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
    )
    projects = sa.Table(
        "projects",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey(organizations.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey(workspaces.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.String(length=36),
            sa.ForeignKey(users.c.id, ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=240), nullable=False),
    )
    sa.Table(
        "workflows",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey(organizations.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey(projects.c.id, ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
    )
    sa.Table(
        "meetings",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey(organizations.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey(projects.c.id, ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "organizer_id",
            sa.String(length=36),
            sa.ForeignKey(users.c.id, ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=240), nullable=False),
    )
    sa.Table(
        "audit_events",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey(organizations.c.id, ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey(users.c.id, ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=160), nullable=False),
        sa.Column("resource_id", sa.String(length=120), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    sa.Table(
        "backup_records",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    return metadata


def _insert_legacy_sentinels(connection: Connection, legacy: sa.MetaData) -> dict:
    sentinel = {
        "organization_id": str(uuid.uuid4()),
        "role_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "project_id": str(uuid.uuid4()),
        "workflow_id": str(uuid.uuid4()),
        "meeting_id": str(uuid.uuid4()),
        "audit_id": str(uuid.uuid4()),
        "backup_id": str(uuid.uuid4()),
        "backup_size_bytes": 2_000_000_000,
        "audit_resource_id": "legacy-resource-" + ("x" * 96),
    }
    connection.execute(
        legacy.tables["organizations"]
        .insert()
        .values(
            id=sentinel["organization_id"],
            name="Legacy Organization",
        )
    )
    connection.execute(
        legacy.tables["roles"]
        .insert()
        .values(
            id=sentinel["role_id"],
            organization_id=sentinel["organization_id"],
            name="Legacy Owner",
        )
    )
    connection.execute(
        legacy.tables["users"]
        .insert()
        .values(
            id=sentinel["user_id"],
            organization_id=sentinel["organization_id"],
            role_id=sentinel["role_id"],
            email="legacy-owner@example.test",
        )
    )
    connection.execute(
        legacy.tables["workspaces"]
        .insert()
        .values(
            id=sentinel["workspace_id"],
            organization_id=sentinel["organization_id"],
            name="Legacy Workspace",
        )
    )
    connection.execute(
        legacy.tables["projects"]
        .insert()
        .values(
            id=sentinel["project_id"],
            organization_id=sentinel["organization_id"],
            workspace_id=sentinel["workspace_id"],
            owner_id=sentinel["user_id"],
            name="Legacy Project",
        )
    )
    connection.execute(
        legacy.tables["workflows"]
        .insert()
        .values(
            id=sentinel["workflow_id"],
            organization_id=sentinel["organization_id"],
            project_id=sentinel["project_id"],
            name="Legacy Workflow",
            steps=[{"type": "legacy"}],
        )
    )
    connection.execute(
        legacy.tables["meetings"]
        .insert()
        .values(
            id=sentinel["meeting_id"],
            organization_id=sentinel["organization_id"],
            project_id=sentinel["project_id"],
            organizer_id=sentinel["user_id"],
            title="Legacy Meeting",
        )
    )
    connection.execute(
        legacy.tables["audit_events"]
        .insert()
        .values(
            id=sentinel["audit_id"],
            organization_id=sentinel["organization_id"],
            user_id=sentinel["user_id"],
            action="legacy.created",
            resource_id=sentinel["audit_resource_id"],
            details={"source": "60ff89a"},
        )
    )
    now = datetime.now(timezone.utc)
    connection.execute(
        legacy.tables["backup_records"]
        .insert()
        .values(
            id=sentinel["backup_id"],
            kind="legacy-full",
            scope="platform",
            status="completed",
            location="/legacy/backup.dump",
            checksum="a" * 64,
            size_bytes=sentinel["backup_size_bytes"],
            completed_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    return sentinel


def _foreign_key(
    inspector: sa.Inspector,
    table_name: str,
    column_name: str,
) -> dict:
    return next(
        foreign_key
        for foreign_key in inspector.get_foreign_keys(table_name)
        if column_name in foreign_key["constrained_columns"]
    )


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        index["name"]
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }


def test_postgres_legacy_schema_upgrades_in_isolated_schema() -> None:
    """Run the real 60ff89a-to-head upgrade against PostgreSQL."""
    admin_engine = _postgres_test_engine()
    schema_name = f"owner_upgrade_{uuid.uuid4().hex}"
    schema_created = False
    isolated_engine: Engine | None = None

    try:
        try:
            with admin_engine.begin() as connection:
                connection.execute(sa.schema.CreateSchema(schema_name))
            schema_created = True
        except (InterfaceError, OperationalError) as error:
            pytest.skip(
                "PostgreSQL is not reachable for the migration test "
                f"({type(error).__name__})"
            )

        isolated_engine = sa.create_engine(
            admin_engine.url,
            connect_args={"options": f"-csearch_path={schema_name}"},
        )
        legacy = _legacy_metadata()
        migration = _load_owner_migration()
        runtime_safety_migration = _load_runtime_safety_migration()

        with isolated_engine.begin() as connection:
            assert connection.execute(
                sa.text("SELECT current_schema()")
            ).scalar_one() == (schema_name)
            legacy.create_all(connection)
            sentinel = _insert_legacy_sentinels(connection, legacy)

            migration_context = MigrationContext.configure(
                connection,
                opts={"version_table_schema": schema_name},
            )
            migration_context.stamp(_script_directory(), "20260726_0001")
            assert migration_context.get_current_heads() == ("20260726_0001",)

            migration.op = Operations(migration_context)
            migration.upgrade()
            migration.upgrade()
            migration_context.stamp(_script_directory(), "20260729_0002")
            assert migration_context.get_current_heads() == ("20260729_0002",)

            inspector = sa.inspect(connection)
            assert "auth_version" not in {
                column["name"] for column in inspector.get_columns("users")
            }
            legacy_backup_size = next(
                column
                for column in inspector.get_columns("backup_records")
                if column["name"] == "size_bytes"
            )
            assert not isinstance(legacy_backup_size["type"], sa.BigInteger)

            runtime_safety_migration.op = Operations(migration_context)
            runtime_safety_migration.upgrade()
            runtime_safety_migration.upgrade()
            migration_context.stamp(_script_directory(), "20260729_0003")
            assert migration_context.get_current_heads() == ("20260729_0003",)

            inspector = sa.inspect(connection)
            assert {
                "organizations",
                "users",
                "workspaces",
                "projects",
                "roles",
                "workflows",
                "meetings",
                "audit_events",
                "backup_records",
                "owner_control_records",
                "owner_command_records",
            }.issubset(inspector.get_table_names())

            for table_name, sentinel_key in (
                ("organizations", "organization_id"),
                ("roles", "role_id"),
                ("users", "user_id"),
                ("workspaces", "workspace_id"),
                ("projects", "project_id"),
                ("workflows", "workflow_id"),
                ("meetings", "meeting_id"),
                ("audit_events", "audit_id"),
                ("backup_records", "backup_id"),
            ):
                assert (
                    connection.execute(
                        sa.text(f"SELECT count(*) FROM {table_name} WHERE id = :id"),
                        {"id": sentinel[sentinel_key]},
                    ).scalar_one()
                    == 1
                )

            role_columns = {
                column["name"]: column for column in inspector.get_columns("roles")
            }
            assert role_columns["status"]["nullable"] is False
            assert (
                connection.execute(
                    sa.text("SELECT status FROM roles WHERE id = :id"),
                    {"id": sentinel["role_id"]},
                ).scalar_one()
                == "active"
            )
            assert "ix_roles_status" in _index_names(inspector, "roles")

            user_columns = {
                column["name"]: column for column in inspector.get_columns("users")
            }
            assert user_columns["auth_version"]["nullable"] is False
            assert (
                connection.execute(
                    sa.text("SELECT auth_version FROM users WHERE id = :id"),
                    {"id": sentinel["user_id"]},
                ).scalar_one()
                == 0
            )

            workflow_columns = {
                column["name"]: column for column in inspector.get_columns("workflows")
            }
            assert workflow_columns["workspace_id"]["nullable"] is True
            assert (
                _foreign_key(inspector, "workflows", "workspace_id")["referred_table"]
                == "workspaces"
            )
            assert (
                connection.execute(
                    sa.text("SELECT workspace_id FROM workflows WHERE id = :id"),
                    {"id": sentinel["workflow_id"]},
                ).scalar_one()
                == sentinel["workspace_id"]
            )
            assert "ix_workflows_workspace_id" in _index_names(inspector, "workflows")

            meeting_columns = {
                column["name"]: column for column in inspector.get_columns("meetings")
            }
            assert meeting_columns["workspace_id"]["nullable"] is True
            assert isinstance(meeting_columns["attendee_ids"]["type"], sa.JSON)
            assert meeting_columns["attendee_ids"]["nullable"] is False
            assert (
                _foreign_key(inspector, "meetings", "workspace_id")["referred_table"]
                == "workspaces"
            )
            assert (
                connection.execute(
                    sa.text("SELECT attendee_ids FROM meetings WHERE id = :id"),
                    {"id": sentinel["meeting_id"]},
                ).scalar_one()
                == []
            )
            assert "ix_meetings_workspace_id" in _index_names(inspector, "meetings")

            audit_columns = {
                column["name"]: column
                for column in inspector.get_columns("audit_events")
            }
            assert audit_columns["resource_id"]["type"].length == 160
            audit_row = (
                connection.execute(
                    sa.text(
                        "SELECT resource_id, details FROM audit_events WHERE id = :id"
                    ),
                    {"id": sentinel["audit_id"]},
                )
                .mappings()
                .one()
            )
            assert audit_row["resource_id"] == sentinel["audit_resource_id"]
            assert audit_row["details"] == {"source": "60ff89a"}

            backup_columns = {
                column["name"]: column
                for column in inspector.get_columns("backup_records")
            }
            assert isinstance(backup_columns["size_bytes"]["type"], sa.BigInteger)
            assert (
                connection.execute(
                    sa.text("SELECT size_bytes FROM backup_records WHERE id = :id"),
                    {"id": sentinel["backup_id"]},
                ).scalar_one()
                == sentinel["backup_size_bytes"]
            )

            owner_control = sa.Table(
                "owner_control_records",
                sa.MetaData(),
                autoload_with=connection,
            )
            owner_command = sa.Table(
                "owner_command_records",
                sa.MetaData(),
                autoload_with=connection,
            )
            assert isinstance(owner_control.c.payload.type, sa.JSON)
            assert isinstance(owner_command.c.request.type, sa.JSON)
            assert isinstance(owner_command.c.result.type, sa.JSON)
            assert (
                _foreign_key(inspector, "owner_command_records", "actor_id")[
                    "referred_table"
                ]
                == "users"
            )
            assert {
                "ix_owner_control_records_domain",
                "ix_owner_control_domain_status",
            }.issubset(_index_names(inspector, "owner_control_records"))
            assert {
                "ix_owner_command_records_actor_id",
                "ix_owner_command_records_created_at",
                "ix_owner_command_domain_created",
                "ix_owner_command_status_created",
            }.issubset(_index_names(inspector, "owner_command_records"))

            now = datetime.now(timezone.utc)
            connection.execute(
                owner_control.insert().values(
                    id=str(uuid.uuid4()),
                    domain="runtime",
                    resource_id="legacy-runtime",
                    status="active",
                    enabled=True,
                    payload={"source": "postgres-migration-test"},
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            command_id = str(uuid.uuid4())
            connection.execute(
                owner_command.insert().values(
                    id=command_id,
                    actor_id=sentinel["user_id"],
                    domain="runtime",
                    resource_id="legacy-runtime",
                    action="validate",
                    status="completed",
                    request={"mode": "live"},
                    result={"healthy": True},
                    created_at=now,
                    completed_at=now,
                )
            )
            command_row = (
                connection.execute(
                    sa.select(
                        owner_command.c.actor_id,
                        owner_command.c.request,
                        owner_command.c.result,
                    ).where(owner_command.c.id == command_id)
                )
                .mappings()
                .one()
            )
            assert command_row == {
                "actor_id": sentinel["user_id"],
                "request": {"mode": "live"},
                "result": {"healthy": True},
            }

            guarded_resource_id = "downgrade-guard-" + ("z" * 125)
            connection.execute(
                sa.text(
                    "UPDATE audit_events SET resource_id = :resource_id WHERE id = :id"
                ),
                {
                    "resource_id": guarded_resource_id,
                    "id": sentinel["audit_id"],
                },
            )
            downgrade_savepoint = connection.begin_nested()
            try:
                with pytest.raises(
                    RuntimeError,
                    match="Cannot downgrade audit_events.resource_id",
                ):
                    migration.downgrade()
            finally:
                downgrade_savepoint.rollback()

            post_guard_inspector = sa.inspect(connection)
            assert {
                "owner_control_records",
                "owner_command_records",
            }.issubset(post_guard_inspector.get_table_names())
            assert (
                next(
                    column
                    for column in post_guard_inspector.get_columns("audit_events")
                    if column["name"] == "resource_id"
                )["type"].length
                == 160
            )
            assert (
                connection.execute(
                    sa.text("SELECT resource_id FROM audit_events WHERE id = :id"),
                    {"id": sentinel["audit_id"]},
                ).scalar_one()
                == guarded_resource_id
            )
    finally:
        if isolated_engine is not None:
            isolated_engine.dispose()
        if schema_created:
            with admin_engine.begin() as connection:
                connection.execute(
                    sa.schema.DropSchema(
                        schema_name,
                        cascade=True,
                        if_exists=True,
                    )
                )
            with admin_engine.connect() as connection:
                assert schema_name not in sa.inspect(connection).get_schema_names()
        admin_engine.dispose()


def test_legacy_owner_schema_upgrades_without_current_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the 0001-to-head DDL path against a minimal legacy schema."""
    monkeypatch.setenv(
        "SECRET_KEY",
        "owner-schema-upgrade-test-secret-key",
    )
    engine = sa.create_engine("sqlite://")
    legacy = sa.MetaData()
    roles = sa.Table(
        "roles",
        legacy,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
    )
    sa.Table(
        "users",
        legacy,
        sa.Column("id", sa.String(length=36), primary_key=True),
    )

    migration = _load_owner_migration()
    runtime_safety_migration = _load_runtime_safety_migration()
    with engine.begin() as connection:
        legacy.create_all(connection)
        connection.execute(roles.insert().values(id="role-1", name="Legacy Owner"))

        script_directory = _script_directory()
        migration_context = MigrationContext.configure(connection)
        migration_context.stamp(script_directory, "20260726_0001")
        assert migration_context.get_current_heads() == ("20260726_0001",)

        migration.op = Operations(migration_context)
        migration.upgrade()
        # The migration is intentionally defensive because the original 0001
        # revision imports live metadata. A second execution must remain safe.
        migration.upgrade()
        migration_context.stamp(script_directory, "20260729_0002")
        assert migration_context.get_current_heads() == ("20260729_0002",)

        runtime_safety_migration.op = Operations(migration_context)
        runtime_safety_migration.upgrade()
        runtime_safety_migration.upgrade()
        migration_context.stamp(script_directory, "20260729_0003")
        assert migration_context.get_current_heads() == ("20260729_0003",)

        inspector = sa.inspect(connection)
        assert {
            "owner_control_records",
            "owner_command_records",
        }.issubset(inspector.get_table_names())
        assert "status" in {column["name"] for column in inspector.get_columns("roles")}
        assert "auth_version" in {
            column["name"] for column in inspector.get_columns("users")
        }
        assert (
            connection.execute(
                sa.text("SELECT status FROM roles WHERE id = 'role-1'")
            ).scalar_one()
            == "active"
        )

        assert "ix_roles_status" in {
            index["name"] for index in inspector.get_indexes("roles")
        }
        assert {
            "ix_owner_control_records_domain",
            "ix_owner_control_domain_status",
        }.issubset(
            {index["name"] for index in inspector.get_indexes("owner_control_records")}
        )
        assert {
            "ix_owner_command_records_actor_id",
            "ix_owner_command_records_created_at",
            "ix_owner_command_domain_created",
            "ix_owner_command_status_created",
        }.issubset(
            {index["name"] for index in inspector.get_indexes("owner_command_records")}
        )
