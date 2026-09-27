"""Real PostgreSQL quota, session and dispatch tests on disposable schemas only.

All principals, projects and provider rows are synthetic. The provider adapter is
an explicit test double in worker-only cases; database locking is never mocked.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.auth import auth_service
from app.db.base import Base
from app.db.models import (
    AIAgent, AIProvider, AuditEvent, Job, Organization, OwnerControlRecord,
    Permission, Project, Role, RolePermission, User, Workspace,
)
from app.services import conversation_governance as g
from app.services import conversation_worker as worker
from app.services import host_maintenance_admission as maintenance


def tables():
    needed = set()

    def visit(table):
        if table.name in needed:
            return
        needed.add(table.name)
        for foreign_key in table.foreign_keys:
            visit(foreign_key.column.table)

    for name in ("owner_control_records", "jobs", "audit_events", "projects", "role_permissions"):
        visit(Base.metadata.tables[name])
    return [t for t in Base.metadata.sorted_tables if t.name in needed]


@pytest_asyncio.fixture
async def case(monkeypatch):
    url = make_url(os.environ["DATABASE_URL"])
    assert os.environ.get("ENVIRONMENT") == "test"
    assert url.drivername == "postgresql+asyncpg"
    assert re.search(r"(?:^|[_-])(?:test|pytest|ci|smoke|disposable)(?:[_-]|$)", url.database or "")
    schema = "fr07_conversations_"+uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"server_settings": {
        "search_path": schema, "statement_timeout": "5000",
    }})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    state = SimpleNamespace(sessions=sessions, users=[], projects=[], workspaces=[], agents=[], provider_calls=[])
    monkeypatch.setattr(worker, "SessionLocal", sessions)

    async def synthetic_provider(provider, agent, prompt):
        state.provider_calls.append({"provider_id": provider.id, "agent_id": agent.id, "prompt": prompt})
        return {"text": "Synthetic adapter result", "provider": "ollama", "model": "synthetic-test", "usage": {"total_tokens": 7}, "cost": 0}

    monkeypatch.setattr(worker.ai, "_execute_provider", synthetic_provider)
    created = False
    try:
        async with admin.begin() as c:
            await c.execute(CreateSchema(schema))
            created = True
        async with engine.begin() as c:
            await c.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables()))
        async with sessions() as s, s.begin():
            s.add(OwnerControlRecord(id=str(uuid4()), domain=maintenance.DOMAIN,
                resource_id=maintenance.RESOURCE_ID, status="open", enabled=True, version=16,
                payload={"schema_version": 8, "scope": maintenance.REALTIME_REQUEST_COVERAGE_SCOPE,
                         "generation": 16, "operation_id": str(uuid4()), "reason": "isolated governance acceptance",
                         "changed_at": datetime.now(UTC).isoformat(), "full_host_closure": False}))
            write = Permission(id=str(uuid4()), code="projects:write")
            wildcard = Permission(id=str(uuid4()), code="*")
            s.add_all([write, wildcard])
            for index in range(3):
                org = Organization(id=str(uuid4()), name="Synthetic tenant", slug=uuid4().hex, plan="enterprise")
                s.add(org)
                await s.flush()
                role = Role(id=str(uuid4()), organization_id=org.id,
                            name="Super Owner" if index == 0 else "Builder")
                s.add(role)
                await s.flush()
                user = User(id=str(uuid4()), organization_id=org.id, role_id=role.id, name="Synthetic user",
                            email=uuid4().hex+"@example.invalid", password_hash="unused-test-hash")
                space = Workspace(id=str(uuid4()), organization_id=org.id, name="Test workspace", slug=uuid4().hex)
                s.add_all([user, space, RolePermission(role_id=role.id,
                    permission_id=wildcard.id if index == 0 else write.id)])
                await s.flush()
                project = Project(id=str(uuid4()), organization_id=org.id, workspace_id=space.id,
                                  owner_id=user.id, name="Synthetic project", slug=uuid4().hex)
                provider = AIProvider(id=str(uuid4()), organization_id=org.id, name="Synthetic provider",
                                      type="ollama", base_url="http://ollama:11434", config={"enabled": True})
                s.add_all([project, provider])
                await s.flush()
                agent = AIAgent(id=str(uuid4()), organization_id=org.id, workspace_id=space.id,
                    provider_id=provider.id, name="Synthetic assistant", slug=uuid4().hex,
                    role="Assistant", department="Tests", model="synthetic-test", status="idle")
                s.add(agent)
                await s.flush()
                state.users.append(await auth_service.get_user_by_id(s, user.id))
                state.projects.append(project.id)
                state.workspaces.append(space.id)
                state.agents.append(agent.id)
        state.owner, state.actor, state.other = state.users
        yield state
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as c:
                await c.execute(DropSchema(schema, cascade=True))
        await admin.dispose()


async def policy(case, values, scope="global", identifier="default"):
    async with case.sessions() as s, s.begin():
        key = g.scope_key(scope, identifier)
        row = await g._record(s, g.POLICY, key)
        return await g.update_policy(s, case.owner, scope=scope, identifier=identifier,
                                     values=values, expected_version=row.version if row else 0)


async def create(case, actor=None, project_id=None, request_id=None):
    actor = actor or case.actor
    async with case.sessions() as s, s.begin():
        return await g.create_thread(s, actor, project_id=project_id or case.projects[1],
                                     title="Synthetic conversation", request_id=request_id or uuid4().hex)


async def send(case, conversation, *, actor=None, request_id=None, message="Synthetic request", agent_id=None):
    actor = actor or case.actor
    async with case.sessions() as s, s.begin():
        return await g.send_message(s, actor, conversation["id"], message=message,
            request_id=request_id or uuid4().hex, agent_id=agent_id or case.agents[1],
            confirm_external_processing=False)


async def usage(case):
    async with case.sessions() as s:
        return (await g.usage_snapshot(s, case.actor))["usage"]


@pytest.mark.asyncio
async def test_default_plan_user_hierarchy_and_disable_is_fail_closed(case):
    await policy(case, {"messages_per_day": 100, "priority": 10})
    await policy(case, {"messages_per_day": 20}, "plan", "enterprise")
    await policy(case, {"messages_per_day": 5, "priority": 90}, "user", case.actor.id)
    async with case.sessions() as s:
        p = (await g.effective_policy(s, case.actor))["values"]
        assert p["messages_per_day"] == 5 and p["priority"] == 90
    await policy(case, {"enabled": False})
    await policy(case, {"enabled": True}, "user", case.actor.id)
    with pytest.raises(HTTPException) as exc:
        await create(case)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_stale_owner_update_is_rejected_without_losing_committed_fields(case):
    first = await policy(case, {"messages_per_day": 4})
    await policy(case, {"priority": 80})
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as exc:
            await g.update_policy(s, case.owner, scope="global", identifier="default",
                                  values={"enabled": False}, expected_version=first["version"])
        assert exc.value.status_code == 409
        await s.rollback()
        p = (await g.effective_policy(s, case.actor))["values"]
        assert p["messages_per_day"] == 4 and p["priority"] == 80 and p["enabled"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["global", "plan", "user"])
async def test_suspended_policy_prevents_new_and_existing_turns(case, scope):
    c = await create(case)
    identifier = {"global": "default", "plan": "enterprise", "user": case.actor.id}[scope]
    await policy(case, {"enabled": False}, scope, identifier)
    with pytest.raises(HTTPException) as exc:
        await send(case, c)
    assert exc.value.status_code == 403
    assert (await usage(case))["total_message_credits"] == 0


@pytest.mark.asyncio
async def test_parallel_creations_respect_exact_user_limit(case):
    await policy(case, {"max_open_conversations": 3, "max_open_conversations_per_project": 3})

    async def attempt():
        try:
            await create(case)
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False

    results = await asyncio.wait_for(asyncio.gather(*(attempt() for _ in range(12))), 10)
    assert sum(results) == 3
    async with case.sessions() as s:
        assert len(await g.list_threads(s, case.actor)) == 3


@pytest.mark.asyncio
async def test_project_conversation_limit_and_other_user_isolation(case):
    await policy(case, {"max_open_conversations_per_project": 1})
    await create(case)
    with pytest.raises(HTTPException) as exc:
        await create(case)
    assert exc.value.status_code == 429
    other = await create(case, actor=case.other, project_id=case.projects[2])
    assert other["user_id"] == case.other.id


@pytest.mark.asyncio
async def test_idempotent_creation_returns_one_identical_conversation(case):
    key = uuid4().hex
    first = await create(case, request_id=key)
    second = await create(case, request_id=key)
    assert first["id"] == second["id"]
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as exc:
            await g.create_thread(s, case.actor, project_id=case.projects[1], title="Changed", request_id=key)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_expired_session_does_not_reset_on_reconnect(case):
    await policy(case, {"conversation_seconds": 2})
    c = await create(case)
    async with case.sessions() as s, s.begin():
        row = await g.get_thread(s, case.actor, c["id"], lock=True)
        row.created_at = datetime.now(UTC)-timedelta(seconds=5)
    async with case.sessions() as s:
        snap = (await g.messages(s, case.actor, c["id"]))["conversation"]
        assert snap["effective_status"] == "expired" and snap["seconds_remaining"] == 0
    with pytest.raises(HTTPException) as exc:
        await send(case, c)
    assert exc.value.status_code == 409
    assert (await usage(case))["day_messages"] == 0


@pytest.mark.asyncio
async def test_owner_duration_reduction_applies_without_reopening_connection(case):
    c = await create(case)
    async with case.sessions() as s, s.begin():
        row = await g.get_thread(s, case.actor, c["id"], lock=True)
        row.created_at = datetime.now(UTC)-timedelta(seconds=5)
    await policy(case, {"conversation_seconds": 1})
    with pytest.raises(HTTPException) as exc:
        await send(case, c)
    assert exc.value.detail["code"] == "CONVERSATION_DURATION_EXCEEDED"


@pytest.mark.asyncio
async def test_close_frees_conversation_slot_without_erasing_credit_usage(case):
    await policy(case, {"max_open_conversations": 1, "messages_per_day": 1})
    c = await create(case)
    job = await send(case, c)
    assert await worker.run_turn(job["job_id"])
    async with case.sessions() as s, s.begin():
        await g.change_thread(s, case.actor, c["id"], action="close")
    other = await create(case)
    with pytest.raises(HTTPException) as exc:
        await send(case, other)
    assert exc.value.detail["code"] == "DAILY_MESSAGE_LIMIT"
    assert (await usage(case))["day_messages"] == 1


@pytest.mark.asyncio
async def test_owner_pause_resume_preserves_age_and_message_count(case):
    c = await create(case)
    async with case.sessions() as s, s.begin():
        paused = await g.change_thread(s, case.actor, c["id"], action="pause", owner=case.owner)
    with pytest.raises(HTTPException):
        await send(case, c)
    async with case.sessions() as s, s.begin():
        resumed = await g.change_thread(s, case.actor, c["id"], action="resume", owner=case.owner)
    assert resumed["opened_at"] == paused["opened_at"] == c["opened_at"]
    assert resumed["messages_used"] == 0 and resumed["status"] == "open"


@pytest.mark.asyncio
async def test_user_cannot_override_owner_pause(case):
    c = await create(case)
    async with case.sessions() as s, s.begin():
        await g.change_thread(s, case.actor, c["id"], action="pause", owner=case.owner)
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as exc:
            await g.change_thread(s, case.actor, c["id"], action="resume")
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_identical_turn_retries_reserve_once_and_changed_body_conflicts(case):
    c = await create(case)
    key = uuid4().hex
    one = await send(case, c, request_id=key)
    two = await send(case, c, request_id=key)
    assert one["job_id"] == two["job_id"] and two["duplicate"]
    with pytest.raises(HTTPException) as exc:
        await send(case, c, request_id=key, message="Changed content")
    assert exc.value.status_code == 409
    assert (await usage(case))["total_message_credits"] == 1


@pytest.mark.asyncio
async def test_parallel_identical_turns_commit_exactly_one_job(case):
    c = await create(case)
    key = uuid4().hex
    values = await asyncio.wait_for(asyncio.gather(*(send(case, c, request_id=key) for _ in range(10))), 10)
    assert len({v["job_id"] for v in values}) == 1
    assert sum(not v["duplicate"] for v in values) == 1
    assert (await usage(case))["day_messages"] == 1


@pytest.mark.asyncio
async def test_parallel_distinct_conversations_share_exact_daily_limit(case):
    await policy(case, {"messages_per_day": 3, "max_open_conversations_per_project": 12})
    conversations = [await create(case) for _ in range(10)]

    async def attempt(c):
        try:
            await send(case, c)
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False

    accepted = await asyncio.wait_for(asyncio.gather(*(attempt(c) for c in conversations)), 10)
    assert sum(accepted) == 3 and (await usage(case))["day_messages"] == 3


@pytest.mark.asyncio
async def test_rollback_reservation_leaves_no_job_or_counter(case):
    c = await create(case)
    async with case.sessions() as s:
        await g.send_message(s, case.actor, c["id"], message="Synthetic", request_id=uuid4().hex,
                             agent_id=case.agents[1], confirm_external_processing=False)
        await s.rollback()
    assert (await usage(case))["day_messages"] == 0
    async with case.sessions() as s:
        assert await s.scalar(select(func.count(Job.id))) == 0


@pytest.mark.asyncio
async def test_lifetime_credit_budget_survives_day_rollover(case):
    await policy(case, {"lifetime_message_credits": 1})
    c = await create(case)
    job = await send(case, c)
    assert await worker.run_turn(job["job_id"])
    async with case.sessions() as s, s.begin():
        row = await g._record(s, g.USAGE, case.actor.id, lock=True)
        row.payload = {**row.payload, "day": (datetime.now(UTC)-timedelta(days=1)).date().isoformat()}
    with pytest.raises(HTTPException) as exc:
        await send(case, c)
    assert exc.value.detail["code"] == "MESSAGE_CREDITS_EXHAUSTED"


@pytest.mark.asyncio
async def test_owner_user_exception_increases_limit_without_resetting_count(case):
    await policy(case, {"messages_per_conversation": 1})
    c = await create(case)
    j = await send(case, c)
    await worker.run_turn(j["job_id"])
    with pytest.raises(HTTPException):
        await send(case, c)
    await policy(case, {"messages_per_conversation": 2}, "user", case.actor.id)
    await send(case, c)
    assert (await usage(case))["total_message_credits"] == 2


@pytest.mark.asyncio
async def test_cross_user_thread_and_agent_scope_denied(case):
    c = await create(case)
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as exc:
            await g.messages(s, case.other, c["id"])
        assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await send(case, c, agent_id=case.agents[2])
    assert exc.value.status_code == 404
    assert (await usage(case))["day_messages"] == 0


@pytest.mark.asyncio
async def test_foreign_project_cannot_be_used_to_create_conversation(case):
    with pytest.raises(HTTPException) as exc:
        await create(case, project_id=case.projects[2])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_maintenance_closure_blocks_enqueue_and_freezes_queued_turn(case):
    c = await create(case)
    job = await send(case, c)
    await maintenance.close_admission(operation_id=str(uuid4()), expected_generation=16,
                                     reason="isolated close", session_factory=case.sessions)
    assert await worker.run_turn(job["job_id"]) is False
    with pytest.raises(HTTPException) as exc:
        await create(case)
    assert exc.value.status_code == 503
    assert not case.provider_calls
    async with case.sessions() as s:
        assert (await s.get(Job, job["job_id"])).status == "queued"


@pytest.mark.asyncio
async def test_exact_queued_job_executes_once_and_history_is_durable(case):
    c = await create(case)
    job = await send(case, c)
    results = await asyncio.wait_for(asyncio.gather(worker.run_turn(job["job_id"]), worker.run_turn(job["job_id"])), 10)
    assert sum(results) == 1 and len(case.provider_calls) == 1
    async with case.sessions() as s:
        result = await g.messages(s, case.actor, c["id"])
        assert result["messages"][0]["assistant_message"] == "Synthetic adapter result"
        assert result["messages"][0]["status"] == "completed"
    assert await worker.run_turn(job["job_id"]) is False


@pytest.mark.asyncio
async def test_provider_uncertainty_is_retained_not_replayed(case, monkeypatch):
    c = await create(case)
    job = await send(case, c)

    async def unknown(*_):
        raise TimeoutError("synthetic unknown outcome")

    monkeypatch.setattr(worker.ai, "_execute_provider", unknown)
    assert await worker.run_turn(job["job_id"])
    assert await worker.run_turn(job["job_id"]) is False
    async with case.sessions() as s:
        assert (await s.get(Job, job["job_id"])).status == "needs_review"
    with pytest.raises(HTTPException) as exc:
        await send(case, c)
    assert exc.value.detail["code"] == "CONVERSATION_PROVIDER_RECONCILIATION_REQUIRED"


@pytest.mark.asyncio
async def test_queued_turn_revoked_before_provider_call(case):
    c = await create(case)
    job = await send(case, c)
    await policy(case, {"enabled": False}, "user", case.actor.id)
    assert await worker.run_turn(job["job_id"])
    assert not case.provider_calls
    async with case.sessions() as s:
        assert (await s.get(Job, job["job_id"])).status == "cancelled"


@pytest.mark.asyncio
async def test_expiration_while_queued_prevents_provider_io(case):
    c = await create(case)
    job = await send(case, c)
    await policy(case, {"conversation_seconds": 1})
    async with case.sessions() as s, s.begin():
        row = await g.get_thread(s, case.actor, c["id"], lock=True)
        row.created_at = datetime.now(UTC)-timedelta(seconds=5)
    assert await worker.run_turn(job["job_id"])
    assert not case.provider_calls


@pytest.mark.asyncio
async def test_policy_reset_preserves_usage_and_audit(case):
    p = await policy(case, {"messages_per_day": 1}, "user", case.actor.id)
    c = await create(case)
    await send(case, c)
    async with case.sessions() as s, s.begin():
        await g.reset_policy(s, case.owner, scope="user", identifier=case.actor.id, expected_version=p["version"])
    assert (await usage(case))["total_message_credits"] == 1
    async with case.sessions() as s:
        assert await s.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == "owner.conversation_governance.policy_reset")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [{"messages_per_day": -1}, {"enabled": "false"}, {"unknown": 1}, {"conversation_seconds": 0}])
async def test_invalid_policy_values_rejected_before_commit(case, values):
    with pytest.raises(HTTPException) as exc:
        await policy(case, values)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_malformed_stored_policy_is_unavailable_not_unlimited(case):
    await policy(case, {"messages_per_day": 1})
    async with case.sessions() as s, s.begin():
        row = await g._record(s, g.POLICY, g.GLOBAL, lock=True)
        row.payload = {"schema": 1, "values": {"messages_per_day": "unlimited"}}
    with pytest.raises(HTTPException) as exc:
        await create(case)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_non_owner_cannot_edit_policy(case):
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as exc:
            await g.update_policy(s, case.actor, scope="global", identifier="default", values={"enabled": False}, expected_version=0)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_current_project_limit_blocks_concurrent_count_and_insert(case):
    await policy(case, {"max_projects": 3})

    async def attempt():
        try:
            async with case.sessions() as s, s.begin():
                await g.project_capacity(s, case.actor, case.actor.id)
                s.add(Project(id=str(uuid4()), organization_id=case.actor.organization_id,
                    workspace_id=case.workspaces[1], owner_id=case.actor.id,
                    name="Concurrent project", slug=uuid4().hex))
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False

    results = await asyncio.wait_for(asyncio.gather(*(attempt() for _ in range(10))), 10)
    assert sum(results) == 2
    async with case.sessions() as s:
        assert await s.scalar(select(func.count(Project.id)).where(Project.owner_id == case.actor.id)) == 3


@pytest.mark.asyncio
async def test_status_read_does_not_write_or_rollover_usage(case):
    c = await create(case)
    await send(case, c)
    async with case.sessions() as s, s.begin():
        row = await g._record(s, g.USAGE, case.actor.id, lock=True)
        row.payload = {**row.payload, "day": (datetime.now(UTC)-timedelta(days=1)).date().isoformat()}
        before = dict(row.payload)
    async with case.sessions() as s, s.begin():
        result = await g.usage_snapshot(s, case.actor)
        assert result["usage"]["day_messages"] == 0
    async with case.sessions() as s:
        row = await g._record(s, g.USAGE, case.actor.id)
        assert row.payload == before
