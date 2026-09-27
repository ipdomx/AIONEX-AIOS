"""Independent state-transition regressions; real disposable PostgreSQL only."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import AIProvider, Job, Project, User
from app.services import conversation_governance as g
from app.services import conversation_worker as worker
from tests import test_fr07_governed_conversations as base

case = base.case


@pytest.mark.asyncio
async def test_closed_conversation_resume_cannot_exceed_current_concurrent_cap(case):
    await base.policy(case, {"max_open_conversations": 1, "max_open_conversations_per_project": 1})
    first = await base.create(case)
    async with case.sessions() as s, s.begin():
        await g.change_thread(s, case.actor, first["id"], action="close")
    await base.create(case)
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as rejected:
            await g.change_thread(s, case.actor, first["id"], action="resume", owner=case.owner)
        assert rejected.value.status_code in {409, 429}
        await s.rollback()
    async with case.sessions() as s:
        rows = await g.list_threads(s, case.actor)
        assert sum(row["effective_status"] in {"open", "paused"} for row in rows) == 1


@pytest.mark.asyncio
async def test_new_message_on_archived_project_is_denied_before_charging(case):
    conversation = await base.create(case)
    async with case.sessions() as s, s.begin():
        project = await s.get(Project, case.projects[1])
        project.status = "archived"
    before = await base.usage(case)
    with pytest.raises(HTTPException) as rejected:
        await base.send(case, conversation)
    assert rejected.value.status_code in {403, 404, 409}
    assert await base.usage(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", ["", "x", "x" * 129])
async def test_invalid_request_identity_cannot_be_charged_by_service(case, request_id):
    conversation = await base.create(case)
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as rejected:
            await g.send_message(s, case.actor, conversation["id"], message="synthetic",
                                 request_id=request_id, agent_id=case.agents[1],
                                 confirm_external_processing=False)
        assert rejected.value.status_code == 422
        await s.rollback()
    assert (await base.usage(case))["total_message_credits"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", ["aws_bedrock", "azure_openai"])
async def test_provider_reconfigured_to_deferred_type_is_not_dispatched(case, provider_type):
    conversation = await base.create(case)
    result = await base.send(case, conversation)
    async with case.sessions() as s, s.begin():
        provider = await s.scalar(select(AIProvider).where(AIProvider.organization_id == case.actor.organization_id))
        provider.type = provider_type
        job = await s.get(Job, result["job_id"])
        job.payload = {**job.payload, "external_processing_confirmed": True}
    await worker.run_turn(result["job_id"])
    assert case.provider_calls == []
    async with case.sessions() as s:
        assert (await s.get(Job, result["job_id"])).status == "cancelled"


@pytest.mark.asyncio
async def test_suspended_requester_cannot_create_projects_for_another_owner(case):
    async with case.sessions() as s, s.begin():
        actor_row = await s.get(User, case.actor.id)
        other = User(id=str(uuid4()), organization_id=case.actor.organization_id,
                     role_id=actor_row.role_id, email=uuid4().hex+"@example.invalid",
                     name="Synthetic co-owner", password_hash="not-a-real-password")
        s.add(other)
        await s.flush()
        owner_id = other.id
    await base.policy(case, {"enabled": False}, "user", case.actor.id)
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as rejected:
            await g.project_capacity(s, case.actor, owner_id)
        assert rejected.value.status_code == 403
        await s.rollback()


@pytest.mark.asyncio
async def test_new_lower_conversation_limit_blocks_queued_undispatched_turn(case):
    conversation = await base.create(case)
    result = await base.send(case, conversation)
    await base.policy(case, {"messages_per_conversation": 0})
    await worker.run_turn(result["job_id"])
    assert case.provider_calls == []
    async with case.sessions() as s:
        assert (await s.get(Job, result["job_id"])).status == "cancelled"


@pytest.mark.asyncio
async def test_malformed_usage_is_not_presented_as_valid_credit_state(case):
    conversation = await base.create(case)
    await base.send(case, conversation)
    async with case.sessions() as s, s.begin():
        row = await g._record(s, g.USAGE, case.actor.id, lock=True)
        row.payload = {**row.payload, "total_messages": -100}
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as rejected:
            await g.usage_snapshot(s, case.actor)
        assert rejected.value.status_code == 503


@pytest.mark.asyncio
async def test_revoked_owner_snapshot_cannot_control_conversation(case):
    conversation = await base.create(case)
    async with case.sessions() as s, s.begin():
        owner = await s.get(User, case.owner.id)
        owner.auth_version += 1
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as rejected:
            await g.change_thread(s, case.actor, conversation["id"], action="pause", owner=case.owner)
        assert rejected.value.status_code == 403
        await s.rollback()
    async with case.sessions() as s:
        assert (await g.get_thread(s, case.actor, conversation["id"])).status == "open"


@pytest.mark.asyncio
async def test_owner_can_close_banned_user_conversation_without_reenabling_user(case):
    conversation = await base.create(case)
    async with case.sessions() as s, s.begin():
        user = await s.get(User, case.actor.id)
        user.status = "suspended"
    from app.api.owner.conversation_governance import ConversationAction, control_conversation
    async with case.sessions() as s:
        result = await control_conversation(conversation["id"],
            ConversationAction(action="close", user_id=case.actor.id, note="Isolated administrative closure"),
            actor=case.owner, session=s)
        assert result["status"] == "closed"
    async with case.sessions() as s:
        assert (await s.get(User, case.actor.id)).status == "suspended"


@pytest.mark.asyncio
async def test_owner_project_creation_for_foreign_tenant_respects_target_cap(case):
    await base.policy(case, {"max_projects": 1}, "user", case.actor.id)
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as rejected:
            await g.owner_project_capacity(s, case.owner, case.actor.id)
        assert rejected.value.status_code == 429
        await s.rollback()
    await base.policy(case, {"max_projects": 2}, "user", case.actor.id)
    async with case.sessions() as s, s.begin():
        await g.owner_project_capacity(s, case.owner, case.actor.id)


@pytest.mark.asyncio
async def test_non_owner_cannot_use_administrative_project_capacity(case):
    async with case.sessions() as s:
        with pytest.raises(HTTPException) as rejected:
            await g.owner_project_capacity(s, case.actor, case.other.id)
        assert rejected.value.status_code == 403
        await s.rollback()


@pytest.mark.asyncio
async def test_deleted_accepted_agent_does_not_switch_to_new_default(case):
    conversation = await base.create(case)
    result = await base.send(case, conversation)
    await base.policy(case, {"default_agent_id": case.agents[0]})
    async with case.sessions() as s, s.begin():
        job = await s.get(Job, result["job_id"])
        job.agent_id = None
    await worker.run_turn(result["job_id"])
    assert case.provider_calls == []
    async with case.sessions() as s:
        assert (await s.get(Job, result["job_id"])).status == "cancelled"


@pytest.mark.asyncio
async def test_provider_model_change_after_acceptance_requires_new_request(case):
    from app.db.models import AIAgent
    conversation = await base.create(case)
    result = await base.send(case, conversation)
    async with case.sessions() as s, s.begin():
        agent = await s.get(AIAgent, case.agents[1])
        agent.model = "different-synthetic-model"
    await worker.run_turn(result["job_id"])
    assert case.provider_calls == []
    async with case.sessions() as s:
        assert (await s.get(Job, result["job_id"])).status == "cancelled"


@pytest.mark.asyncio
async def test_existing_non_uuid_user_project_and_assistant_ids_remain_usable(case):
    from app.core.auth import auth_service
    from app.db.models import AIAgent
    suffix = uuid4().hex[:12]
    async with case.sessions() as s, s.begin():
        original = await s.get(User, case.actor.id)
        legacy = User(id="legacy-user-" + suffix, organization_id=case.actor.organization_id,
            role_id=original.role_id, name="Retained legacy user", email=suffix+"@example.invalid",
            password_hash="unused-synthetic")
        s.add(legacy)
        await s.flush()
        project = Project(id="legacy-project-"+suffix, organization_id=legacy.organization_id,
            workspace_id=case.workspaces[1], owner_id=legacy.id, name="Retained legacy project", slug=suffix)
        s.add(project)
        source = await s.get(AIAgent, case.agents[1])
        agent = AIAgent(id="legacy-agent-"+suffix, organization_id=legacy.organization_id,
            workspace_id=case.workspaces[1], provider_id=source.provider_id,
            name="Retained legacy assistant", slug=suffix, role="Assistant", department="Tests",
            model=source.model, status="idle")
        s.add(agent)
        await s.flush()
        actor = await auth_service.get_user_by_id(s, legacy.id)
        pid, aid = project.id, agent.id
    await base.policy(case, {"messages_per_day": 2}, "user", actor.id)
    request_id = uuid4().hex
    async with case.sessions() as s, s.begin():
        conversation = await g.create_thread(s, actor, project_id=pid, title="Legacy continuity", request_id=request_id)
    async with case.sessions() as s, s.begin():
        repeated = await g.create_thread(s, actor, project_id=pid, title="Legacy continuity", request_id=request_id)
        assert repeated["id"] == conversation["id"]
        result = await g.send_message(s, actor, conversation["id"], message="Retained identifiers",
            request_id=uuid4().hex, agent_id=aid, confirm_external_processing=False)
    await worker.run_turn(result["job_id"])
    async with case.sessions() as s:
        assert (await s.get(Job, result["job_id"])).status == "completed"
        assert (await g.usage_snapshot(s, actor))["usage"]["total_message_credits"] == 1


@pytest.mark.parametrize("identifier", ["", "../../user", "user:other", "a" * 37, "a\x00b"])
def test_existing_entity_identifier_validation_stays_bounded(identifier):
    with pytest.raises(HTTPException) as rejected:
        g._entity_id(identifier)
    assert rejected.value.status_code == 422
