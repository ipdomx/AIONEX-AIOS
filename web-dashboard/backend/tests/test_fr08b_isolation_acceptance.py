"""FR08B source acceptance: real disposable PostgreSQL, explicit modeled provider.

No production URI, real provider, deployment, throughput or fair-scheduler claim.
"""

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.auth import auth_service
from app.db.models import Project, User
from app.services import conversation_governance as g
from app.services import conversation_worker as worker
from tests.test_fr07_governed_conversations import create, send, usage

pytest_plugins = ("tests.test_fr07_governed_conversations",)


async def another_project(c):
    async with c.sessions() as s, s.begin():
        row = Project(
            id=str(uuid4()),
            organization_id=c.actor.organization_id,
            workspace_id=c.workspaces[1],
            owner_id=c.actor.id,
            name="Synthetic FR08 project",
            slug=uuid4().hex,
        )
        s.add(row)
        await s.flush()
        return row.id


async def peer(c, same_org):
    if not same_org:
        return c.other, c.projects[2], c.agents[2]
    async with c.sessions() as s, s.begin():
        original = await s.get(User, c.actor.id)
        row = User(
            id=str(uuid4()),
            organization_id=c.actor.organization_id,
            role_id=original.role_id,
            name="Synthetic same-org peer",
            email=uuid4().hex + "@example.invalid",
            password_hash="unused-test-hash",
        )
        s.add(row)
        await s.flush()
        return await auth_service.get_user_by_id(s, row.id), c.projects[1], c.agents[1]


def transcript(prompt):
    return json.loads(prompt.split("\n", 1)[1])


def capture_provider(c, monkeypatch):
    async def provider(provider, agent, prompt):
        messages = transcript(prompt)
        c.provider_calls.append(messages)
        return {
            "text": "reply:" + messages[-1]["content"],
            "provider": "ollama",
            "model": "synthetic-test",
            "cost": 0,
            "usage": {},
        }

    monkeypatch.setattr(worker.ai, "_execute_provider", provider)


async def history(c, actor, thread):
    async with c.sessions() as s:
        return await g.messages(s, actor, thread["id"])


@pytest.mark.asyncio
async def test_three_projects_nine_threads_real_claims_and_isolated_context(
    case, monkeypatch
):
    projects = [
        case.projects[1],
        await another_project(case),
        await another_project(case),
    ]
    threads = []
    for project in projects:
        threads.extend([await create(case, project_id=project) for _ in range(3)])
    assert len({x["id"] for x in threads}) == 9
    markers = ["SYNTHETIC_CTX_" + uuid4().hex for _ in threads]
    calls = []
    state = {
        "active": 0,
        "peak": 0,
        "entered": 0,
        "expected": 0,
        "ready": asyncio.Event(),
        "release": asyncio.Event(),
    }

    async def provider(provider, agent, prompt):
        messages = transcript(prompt)
        calls.append(messages)
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        state["entered"] += 1
        if state["entered"] == state["expected"]:
            state["ready"].set()
        try:
            await state["release"].wait()
        finally:
            state["active"] -= 1
        return {
            "text": "reply:" + messages[-1]["content"],
            "provider": "ollama",
            "model": "synthetic-test",
            "cost": 0,
            "usage": {},
        }

    monkeypatch.setattr(worker.ai, "_execute_provider", provider)
    for turn in [1, 2]:
        accepted = await asyncio.gather(
            *(
                send(case, thread, message=f"{marker}:turn{turn}")
                for thread, marker in zip(threads, markers)
            )
        )
        state.update(
            active=0,
            peak=0,
            entered=0,
            expected=9,
            ready=asyncio.Event(),
            release=asyncio.Event(),
        )
        tasks = [
            asyncio.create_task(worker.run_turn(item["job_id"])) for item in accepted
        ]
        try:
            await asyncio.wait_for(state["ready"].wait(), 12)
            assert state["peak"] == 9
            state["release"].set()
            assert all(await asyncio.wait_for(asyncio.gather(*tasks), 12))
        finally:
            state["release"].set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert len(calls) == 18
    for marker, thread in zip(markers, threads):
        selected = [call for call in calls if call[-1]["content"].startswith(marker)]
        assert len(selected) == 2
        assert selected[0] == [{"role": "user", "content": marker + ":turn1"}]
        assert selected[1] == [
            {"role": "user", "content": marker + ":turn1"},
            {"role": "assistant", "content": "reply:" + marker + ":turn1"},
            {"role": "user", "content": marker + ":turn2"},
        ]
        found = await history(case, case.actor, thread)
        assert found["conversation"]["project_id"] == thread["project_id"]
        assert [x["ordinal"] for x in found["messages"]] == [1, 2]
        assert all(
            marker in item["user_message"] and marker in item["assistant_message"]
            for item in found["messages"]
        )
    assert (await usage(case))["day_messages"] == 18


@pytest.mark.asyncio
@pytest.mark.parametrize("same_org", [False, True])
@pytest.mark.parametrize("action", ["read", "send", "list"])
async def test_other_user_cannot_read_or_send_to_private_thread(
    case, same_org, action
):
    thread = await create(case)
    actor, _project, agent = await peer(case, same_org)
    if action == "list":
        async with case.sessions() as s:
            assert await g.list_threads(s, actor) == []
    else:
        with pytest.raises(HTTPException) as exc:
            if action == "read":
                await history(case, actor, thread)
            else:
                await send(case, thread, actor=actor, agent_id=agent)
        assert exc.value.status_code == 404
    assert case.provider_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("same_org", [False, True])
async def test_same_request_key_across_users_does_not_share_thread_or_history(
    case, monkeypatch, same_org
):
    actor, project, agent = await peer(case, same_org)
    key = uuid4().hex
    a = await create(case, request_id=key)
    b = await create(case, actor=actor, project_id=project, request_id=key)
    assert a["id"] != b["id"]
    capture_provider(case, monkeypatch)
    ja = await send(case, a, request_id=key, message="SYNTHETIC_USER_A")
    jb = await send(
        case,
        b,
        actor=actor,
        agent_id=agent,
        request_id=key,
        message="SYNTHETIC_USER_B",
    )
    assert ja["job_id"] != jb["job_id"]
    assert all(
        await asyncio.gather(
            worker.run_turn(ja["job_id"]), worker.run_turn(jb["job_id"])
        )
    )
    assert {tuple(x["content"] for x in call) for call in case.provider_calls} == {
        ("SYNTHETIC_USER_A",),
        ("SYNTHETIC_USER_B",),
    }
    assert (
        (await history(case, case.actor, a))["messages"][0]["assistant_message"]
        == "reply:SYNTHETIC_USER_A"
    )
    assert (
        (await history(case, actor, b))["messages"][0]["assistant_message"]
        == "reply:SYNTHETIC_USER_B"
    )


@pytest.mark.asyncio
async def test_same_user_creation_key_cannot_silently_switch_project(case):
    other = await another_project(case)
    key = uuid4().hex
    a = await create(case, request_id=key)
    with pytest.raises(HTTPException) as exc:
        await create(case, project_id=other, request_id=key)
    assert exc.value.status_code == 409
    assert (await history(case, case.actor, a))["conversation"]["project_id"] == case.projects[1]


@pytest.mark.asyncio
async def test_same_turn_request_key_is_scoped_per_conversation_and_not_recharged(
    case, monkeypatch
):
    a = await create(case)
    b = await create(case, project_id=await another_project(case))
    key = uuid4().hex
    accepted = await asyncio.gather(
        *(
            send(case, thread, request_id=key, message="SYNTHETIC_IDENTICAL_BODY")
            for thread in [a, a, b, b]
        )
    )
    assert len({x["job_id"] for x in accepted}) == 2
    assert sum(x["duplicate"] for x in accepted) == 2
    assert (await usage(case))["day_messages"] == 2
    capture_provider(case, monkeypatch)
    results = await asyncio.gather(
        *(worker.run_turn(item["job_id"]) for item in accepted)
    )
    assert sum(results) == 2 and len(case.provider_calls) == 2
    for thread in [a, b]:
        assert len((await history(case, case.actor, thread))["messages"]) == 1


@pytest.mark.asyncio
async def test_uncertain_turn_blocks_only_its_thread_without_replaying(
    case, monkeypatch
):
    a = await create(case)
    b = await create(case, project_id=await another_project(case))
    calls = []

    async def provider(provider, agent, prompt):
        messages = transcript(prompt)
        calls.append(messages)
        if messages[-1]["content"] == "SYNTHETIC_UNCERTAIN":
            raise TimeoutError("synthetic provider uncertainty")
        return {
            "text": "SYNTHETIC_OK",
            "provider": "ollama",
            "model": "synthetic-test",
            "cost": 0,
            "usage": {},
        }

    monkeypatch.setattr(worker.ai, "_execute_provider", provider)
    ja = await send(case, a, message="SYNTHETIC_UNCERTAIN")
    jb = await send(case, b, message="SYNTHETIC_READY")
    assert all(
        await asyncio.gather(
            worker.run_turn(ja["job_id"]), worker.run_turn(jb["job_id"])
        )
    )
    assert await worker.run_turn(ja["job_id"]) is False
    with pytest.raises(HTTPException) as exc:
        await send(case, a)
    assert exc.value.detail["code"] == "CONVERSATION_PROVIDER_RECONCILIATION_REQUIRED"
    assert (await history(case, case.actor, a))["messages"][0]["status"] == "needs_review"
    assert (await history(case, case.actor, b))["messages"][0]["status"] == "completed"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_owner_pause_resume_preserves_context_and_does_not_pause_sibling(
    case, monkeypatch
):
    a = await create(case)
    b = await create(case, project_id=await another_project(case))
    capture_provider(case, monkeypatch)
    first = await send(case, a, message="SYNTHETIC_KEPT_A")
    assert await worker.run_turn(first["job_id"])
    before = (await history(case, case.actor, a))["conversation"]
    async with case.sessions() as s, s.begin():
        await g.change_thread(
            s, case.actor, a["id"], action="pause", owner=case.owner
        )
    with pytest.raises(HTTPException) as exc:
        await send(case, a, message="SYNTHETIC_BLOCKED")
    assert exc.value.status_code == 409
    sibling = await send(case, b, message="SYNTHETIC_SIBLING_B")
    assert await worker.run_turn(sibling["job_id"])
    async with case.sessions() as s, s.begin():
        resumed = await g.change_thread(
            s, case.actor, a["id"], action="resume", owner=case.owner
        )
    assert (
        resumed["opened_at"] == before["opened_at"]
        and resumed["messages_used"] == before["messages_used"]
    )
    second = await send(case, a, message="SYNTHETIC_RESUMED_A")
    assert await worker.run_turn(second["job_id"])
    assert case.provider_calls[-1] == [
        {"role": "user", "content": "SYNTHETIC_KEPT_A"},
        {"role": "assistant", "content": "reply:SYNTHETIC_KEPT_A"},
        {"role": "user", "content": "SYNTHETIC_RESUMED_A"},
    ]
    assert (
        (await history(case, case.actor, b))["messages"][0]["assistant_message"]
        == "reply:SYNTHETIC_SIBLING_B"
    )
