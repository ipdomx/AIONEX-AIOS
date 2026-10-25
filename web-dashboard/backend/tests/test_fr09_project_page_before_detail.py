"""Ensure FR09 project paging restricts work before joins, counts, and ORM rows."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql
from app.api.v1.endpoints.projects import list_projects


class EmptyRows:
    def all(self):
        return []


class Capture:
    def __init__(self):
        self.calls = []

    async def execute(self, statement):
        self.calls.append(statement)
        return EmptyRows()


def _statement(*, skip=0, limit=20, status_filter=None, priority=None,
               workspace_id=None, search=None):
    session = Capture()
    actor = SimpleNamespace(
        id="synthetic-user-1", organization_id="synthetic-org-1",
        organization_name="Synthetic Organization",
    )
    result = asyncio.run(list_projects(
        skip=skip, limit=limit, status_filter=status_filter,
        priority=priority, workspace_id=workspace_id, search=search,
        actor=actor, session=session,
    ))
    assert result == []
    assert len(session.calls) == 1
    return session.calls[0]


def test_tenant_page_is_materialized_before_all_detail_and_task_counts():
    query = str(_statement().compile(dialect=postgresql.dialect())).upper()
    assert "WITH PROJECT_PAGE AS MATERIALIZED" in query
    assert query.count("ORGANIZATION_ID") >= 3
    assert "PROJECT_PAGE.ID = PROJECTS.ID" in query
    assert "JOIN WORKSPACES" in query
    assert "JOIN USERS" in query
    assert "TASKS.PROJECT_ID = PROJECTS.ID" in query
    assert "TASKS.ORGANIZATION_ID = PROJECTS.ORGANIZATION_ID" in query
    head, detail = query.split("\n SELECT PROJECTS.ID", maxsplit=1)
    assert "LIMIT" in head and "OFFSET" in head
    assert "TASKS" not in head
    assert "WORKSPACES" not in head
    assert "USERS" not in head
    assert "ORDER BY PROJECTS.CREATED_AT DESC" in head
    assert "ORDER BY PROJECT_PAGE.CREATED_AT DESC" in detail


def test_every_public_list_filter_stays_inside_bounded_tenant_page():
    query = _statement(
        skip=50, limit=15, status_filter="planning", priority="medium",
        workspace_id="synthetic-workspace", search="test project",
    )
    compiled = query.compile(dialect=postgresql.dialect())
    sql = str(compiled).upper()
    head = sql.split("\n SELECT PROJECTS.ID", maxsplit=1)[0]
    for token in (
        "PROJECTS.STATUS", "PROJECTS.PRIORITY", "PROJECTS.WORKSPACE_ID",
        "PROJECTS.NAME", "ILIKE", "PROJECTS.ORGANIZATION_ID",
    ):
        assert token in head
    assert 50 in compiled.params.values()
    assert 15 in compiled.params.values()
    assert "synthetic-org-1" in compiled.params.values()
    assert "test project" in " ".join(str(x) for x in compiled.params.values())


def test_no_filter_is_optional_after_page_selection():
    query = str(_statement().compile(dialect=postgresql.dialect())).upper()
    page_sql = query.split("\n SELECT PROJECTS.ID", maxsplit=1)[0]
    assert "PROJECTS.STATUS !=" in page_sql
    assert "PROJECTS.ORGANIZATION_ID =" in page_sql
    assert "LIMIT" in page_sql
