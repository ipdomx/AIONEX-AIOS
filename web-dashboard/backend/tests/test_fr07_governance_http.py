"""Real FastAPI governance routes against disposable PostgreSQL.

Authentication fixtures supply synthetic principals; route RBAC, validation,
transactions and counter enforcement are not mocked. Real JWT/WebSocket behavior
is exercised separately by the event-stream tests and image/browser canaries.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.owner import conversation_governance as owner_routes
from app.api.v1.endpoints import project_conversations as user_routes
from app.core.auth import current_user
from app.db.base import get_db
from tests import test_fr07_governed_conversations as base

case = base.case


@asynccontextmanager
async def client(case, actor):
    app = FastAPI()
    app.include_router(owner_routes.router, prefix="/api/v1")
    app.include_router(user_routes.router, prefix="/api/v1/project-conversations")

    async def database():
        async with case.sessions() as session:
            yield session

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[current_user] = lambda: actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://isolated.test") as transport:
        yield transport


@pytest.mark.asyncio
async def test_owner_directory_wire_contract_and_ordinary_user_denial(case):
    async with client(case, case.actor) as c:
        assert (await c.get("/api/v1/owner/conversation-governance")).status_code == 403
    async with client(case, case.owner) as c:
        result = await c.get("/api/v1/owner/conversation-governance")
        assert result.status_code == 200
        body = result.json()
        assert {"defaults", "policies", "users", "assistants"} <= set(body)
        assert {u["id"] for u in body["users"]} == {case.owner.id, case.actor.id, case.other.id}
        assert {a["id"] for a in body["assistants"]} == {case.agents[0]}
        assert all(set(a) == {"id", "name", "model", "provider", "configured"} for a in body["assistants"])
        assert not any(word in result.text for word in ["password_hash", "api_key", "api_secret", "credentials"])


@pytest.mark.asyncio
async def test_policy_put_has_compare_and_swap_and_unsupported_values_fail(case):
    path = "/api/v1/owner/conversation-governance/policies/user/" + case.actor.id
    async with client(case, case.owner) as c:
        created = await c.put(path, json={"expected_version": 0, "values": {"messages_per_day": 2}})
        assert created.status_code == 200
        version = created.json()["version"]
        assert (await c.put(path, json={"expected_version": 0, "values": {"enabled": False}})).status_code == 409
        assert (await c.put(path, json={"expected_version": version, "values": {"made_up_limit": 0}})).status_code == 422
        current = await c.get("/api/v1/owner/conversation-governance/users/" + case.actor.id)
        assert current.status_code == 200 and current.json()["values"]["messages_per_day"] == 2
        assert current.json()["values"]["enabled"] is True


@pytest.mark.asyncio
async def test_http_duplicate_send_charges_once_and_next_message_limit_is_enforced(case):
    await base.policy(case, {"messages_per_conversation": 1})
    async with client(case, case.actor) as c:
        created = await c.post("/api/v1/project-conversations", json={
            "project_id": case.projects[1], "title": "Synthetic HTTP conversation", "request_id": uuid4().hex})
        assert created.status_code == 201
        cid = created.json()["id"]
        payload = {"message": "Synthetic HTTP prompt", "request_id": uuid4().hex,
                   "agent_id": case.agents[1], "confirm_external_processing": False}
        first = await c.post(f"/api/v1/project-conversations/{cid}/messages", json=payload)
        assert first.status_code == 202
        repeated = await c.post(f"/api/v1/project-conversations/{cid}/messages", json=payload)
        assert repeated.status_code == 202
        assert first.json()["job_id"] == repeated.json()["job_id"]
        assert repeated.json()["duplicate"] is True
        from app.services import conversation_worker
        await conversation_worker.run_turn(first.json()["job_id"])
        denied = await c.post(f"/api/v1/project-conversations/{cid}/messages", json={**payload, "request_id": uuid4().hex})
        assert denied.status_code == 429
        detail = (await c.get(f"/api/v1/project-conversations/{cid}/messages")).json()
        assert detail["conversation"]["messages_used"] == 1 and len(detail["messages"]) == 1
        assert detail["messages"][0]["status"] == "completed"
    assert (await base.usage(case))["total_message_credits"] == 1


@pytest.mark.asyncio
async def test_private_thread_is_not_readable_or_mutable_from_other_tenant(case):
    thread = await base.create(case)
    path = "/api/v1/project-conversations/" + thread["id"]
    async with client(case, case.other) as c:
        assert (await c.get(path + "/messages")).status_code == 404
        assert (await c.post(path + "/close")).status_code == 404
    async with client(case, case.actor) as c:
        assert (await c.get(path + "/messages")).json()["conversation"]["status"] == "open"


@pytest.mark.asyncio
async def test_owner_suspension_blocks_following_http_message_without_usage_reset(case):
    thread = await base.create(case)
    async with client(case, case.owner) as c:
        path = "/api/v1/owner/conversation-governance/policies/user/" + case.actor.id
        assert (await c.put(path, json={"expected_version": 0, "values": {"enabled": False}})).status_code == 200
    async with client(case, case.actor) as c:
        response = await c.post("/api/v1/project-conversations/" + thread["id"] + "/messages", json={
            "message": "Must not dispatch", "agent_id": case.agents[1], "request_id": uuid4().hex})
        assert response.status_code == 403
    assert (await base.usage(case))["total_message_credits"] == 0
