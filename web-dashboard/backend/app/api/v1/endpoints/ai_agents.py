"""Durable AI agent orchestration endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.core.owner_policy import require_owner_service_allowed
from app.db.base import get_db
from app.services import ai_runtime_service

router = APIRouter()


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=120)
    department: str = Field(min_length=1, max_length=120)
    provider_id: str
    model: str = Field(min_length=1, max_length=160)
    system_prompt: Optional[str] = Field(default=None, max_length=20000)
    organization_id: Optional[str] = None
    workspace_id: Optional[str] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    role: Optional[str] = Field(default=None, min_length=1, max_length=120)
    status: Optional[str] = None
    system_prompt: Optional[str] = Field(default=None, max_length=20000)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    model: Optional[str] = Field(default=None, min_length=1, max_length=160)


class AgentExecutionRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=50000)


@router.get("")
async def list_agents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    provider: Optional[str] = None,
    role: Optional[str] = None,
    search: Optional[str] = None,
    user: UserRecord = Depends(require_permissions("agents:read")),
    session: AsyncSession = Depends(get_db),
):
    return await ai_runtime_service.list_agents(
        session,
        user.organization_id,
        status=status,
        provider_name=provider,
        role=role,
        search=search,
        skip=skip,
        limit=limit,
    )


@router.post("", status_code=201)
async def create_agent(
    data: AgentCreate,
    user: UserRecord = Depends(require_permissions("agents:write")),
    session: AsyncSession = Depends(get_db),
):
    provider = await ai_runtime_service.get_provider(
        session, data.provider_id, user.organization_id
    )
    await require_owner_service_allowed(session, provider.type)
    payload = data.model_dump(exclude={"organization_id"})
    return await ai_runtime_service.create_agent(
        session, payload, user.organization_id, user.id
    )


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    user: UserRecord = Depends(require_permissions("agents:read")),
    session: AsyncSession = Depends(get_db),
):
    agent, provider = await ai_runtime_service.get_agent(
        session, agent_id, user.organization_id
    )
    return ai_runtime_service.agent_snapshot(agent, provider)


@router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    data: AgentUpdate,
    user: UserRecord = Depends(require_permissions("agents:write")),
    session: AsyncSession = Depends(get_db),
):
    return await ai_runtime_service.update_agent(
        session,
        agent_id,
        user.organization_id,
        data.model_dump(exclude_unset=True),
        user.id,
    )


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    user: UserRecord = Depends(require_permissions("agents:write")),
    session: AsyncSession = Depends(get_db),
):
    await ai_runtime_service.delete_agent(
        session, agent_id, user.organization_id, user.id
    )
    return {"message": "Agent deleted successfully"}


@router.post("/{agent_id}/execute", status_code=202)
async def execute_agent(
    agent_id: str,
    data: AgentExecutionRequest,
    background_tasks: BackgroundTasks,
    user: UserRecord = Depends(require_permissions("agents:write")),
    session: AsyncSession = Depends(get_db),
):
    _, provider = await ai_runtime_service.get_agent(
        session, agent_id, user.organization_id
    )
    await require_owner_service_allowed(session, provider.type)
    job = await ai_runtime_service.create_job(
        session, agent_id, user.organization_id, data.prompt, user.id
    )
    background_tasks.add_task(ai_runtime_service.run_job, job.id)
    return ai_runtime_service.job_snapshot(job)


@router.get("/{agent_id}/tasks")
async def get_agent_tasks(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: UserRecord = Depends(require_permissions("agents:read")),
    session: AsyncSession = Depends(get_db),
):
    return await ai_runtime_service.list_agent_jobs(
        session, agent_id, user.organization_id, limit=limit
    )


@router.get("/{agent_id}/knowledge")
async def get_agent_knowledge(
    agent_id: str,
    user: UserRecord = Depends(require_permissions("agents:read")),
    session: AsyncSession = Depends(get_db),
):
    agent, _ = await ai_runtime_service.get_agent(
        session, agent_id, user.organization_id
    )
    return {
        "agent_id": agent.id,
        "system_prompt": agent.system_prompt,
        "sources": [],
    }
