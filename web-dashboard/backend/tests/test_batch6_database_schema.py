from app.db.base import Base
from app.db import models  # noqa: F401


def test_expected_tables_are_registered():
    expected = {
        "organizations",
        "roles",
        "permissions",
        "role_permissions",
        "users",
        "refresh_sessions",
        "workspaces",
        "projects",
        "tasks",
        "workflows",
        "meetings",
        "reports",
        "ai_providers",
        "ai_agents",
        "jobs",
        "notifications",
        "audit_events",
        "metric_samples",
        "alerts",
        "backup_records",
        "disaster_recovery_runs",
    }
    assert expected.issubset(set(Base.metadata.tables))


def test_core_unique_constraints_and_indexes_exist():
    users = Base.metadata.tables["users"]
    projects = Base.metadata.tables["projects"]
    assert any(column.name == "email" and column.unique for column in users.columns)
    assert any(index.name == "ix_projects_org_status_priority" for index in projects.indexes)
