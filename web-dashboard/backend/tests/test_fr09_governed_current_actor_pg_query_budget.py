"""Measure true SQL roundtrips using isolated PostgreSQL and real actor records."""


import pytest
from sqlalchemy import event

from tests import test_fr07_governed_conversations as base
from app.services import conversation_governance as g

case = base.case


@pytest.mark.asyncio
async def test_readonly_conversation_auth_is_exactly_two_live_selects(case):
    async with case.sessions() as session:
        engine = case.sessions.kw["bind"]
        statements = []

        def capture(conn, cursor, statement, params, context, many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        try:
            actor = await g.current_actor(session, case.actor, lock=False)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture)
        assert actor.id == case.actor.id
        assert actor.organization_id == case.actor.organization_id
        assert actor.permissions == case.actor.permissions
        assert len(statements) == 2
        assert "role_permissions" in statements[1]


@pytest.mark.asyncio
async def test_locked_conversation_auth_preserves_select_for_update_in_three_selects(case):
    async with case.sessions() as session:
        engine = case.sessions.kw["bind"]
        statements = []

        def capture(conn, cursor, statement, params, context, many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        try:
            actor = await g.current_actor(session, case.actor, lock=True)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture)
        assert actor.id == case.actor.id
        assert len(statements) == 3
        assert "FOR UPDATE" in statements[0].upper()
        assert "role_permissions" in statements[-1]

