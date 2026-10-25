"""FR09 live policies and user-owned conversations share one PostgreSQL read."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from uuid import uuid4

from app.db.models import OwnerControlRecord, Role
from app.services import conversation_governance as governance
from tests import test_fr07_governed_conversations as base

pytest_plugins = ("tests.test_fr07_governed_conversations",)
case = base.case


@pytest.mark.asyncio
async def test_current_user_and_policy_threads_use_two_actual_selects(case):
    created = [await base.create(case) for _ in range(3)]
    async with case.sessions() as session:
        engine = case.sessions.kw["bind"]
        statements = []

        def capture(conn, cursor, statement, params, context, many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        try:
            rows = await governance.list_threads(session, case.actor)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert {x["id"] for x in rows} == {x["id"] for x in created}
    assert len(statements) == 2
    assert "role_permissions" in statements[0].lower()
    assert "owner_control_records" in statements[1].lower()
    assert "clock_timestamp()" in statements[1].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("layer", ["global", "plan", "user"])
async def test_layer_suspension_blocks_existing_inbox(case, layer):
    await base.create(case)
    key = {"global": "default", "plan": "enterprise", "user": case.actor.id}[layer]
    await base.policy(case, {"enabled": False}, layer, key)
    if layer == "global":
        await base.policy(case, {"enabled": True}, "user", case.actor.id)
    async with case.sessions() as session:
        with pytest.raises(HTTPException) as error:
            await governance.list_threads(session, case.actor)
        assert error.value.status_code == 403
        assert error.value.detail["code"] == "OWNER_ACCESS_SUSPENDED"


@pytest.mark.asyncio
async def test_user_scope_project_filter_and_policy_precedence(case):
    a = await base.create(case)
    await base.create(case, actor=case.other, project_id=case.projects[2])
    await base.policy(case, {"priority": 78}, "user", case.actor.id)
    async with case.sessions() as session:
        selected = await governance.list_threads(session, case.actor, case.projects[1])
        assert len(selected) == 1
        assert selected[0]["id"] == a["id"]
        assert selected[0]["priority"] == 78
        assert await governance.list_threads(session, case.actor, case.projects[2]) == []
        with pytest.raises(HTTPException) as error:
            await governance.list_threads(session, case.actor, "invalid;project")
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_suspended_live_role_never_uses_cached_permission(case):
    async with case.sessions() as session, session.begin():
        from app.db.models import User
        user = await session.get(User, case.actor.id)
        role = await session.get(Role, user.role_id)
        role.status = "suspended"
    async with case.sessions() as session:
        with pytest.raises(HTTPException) as error:
            await governance.list_threads(session, case.actor)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_inbox_limit_remains_1000_when_policy_has_fewer_than_three_rows(case):
    sample = await base.create(case)
    async with case.sessions() as session:
        existing = await governance._record(
            session, governance.thread_domain(case.actor.id), sample["id"]
        )
        assert existing is not None
        content = dict(existing.payload)
    async with case.sessions() as session, session.begin():
        session.add_all(
            OwnerControlRecord(
                id=str(uuid4()),
                domain=governance.thread_domain(case.actor.id),
                resource_id=str(uuid4()),
                status="open",
                enabled=True,
                version=1,
                payload={**content, "title": "synthetic test thread"},
            )
            for _ in range(1002)
        )
    async with case.sessions() as session:
        threads = await governance.list_threads(session, case.actor)
        assert len(threads) == 1000
        assert len({x["id"] for x in threads}) == 1000
