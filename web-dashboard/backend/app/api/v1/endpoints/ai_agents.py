"""AI agent orchestration endpoints."""

import asyncio
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel

from app.core.ai_runtime import ai_runtime
from app.core.auth import UserRecord, current_user

router = APIRouter()


class AgentCreate(BaseModel):
    name: str
    role: str
    department: str
    provider_id: str
    model: str
    system_prompt: Optional[str] = None
    organization_id: Optional[str] = None
    workspace_id: Optional[str] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None


class AgentExecutionRequest(BaseModel):
    prompt: str


@router.get("")
async def list_agents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    provider: Optional[str] = None,
    role: Optional[str] = None,
    search: Optional[str] = None,
    user: UserRecord = Depends(current_user),
):
    rows = ai_runtime.list_agents(user.organization_id)
    if status:
        rows = [row for row in rows if row["status"] == status]
    if provider:
        rows = [row for row in rows if row["provider"].lower() == provider.lower()]
    if role:
        rows = [row for row in rows if row["role"].lower() == role.lower()]
    if search:
        needle = search.lower()
        rows = [row for row in rows if needle in row["name"].lower() or needle in row["role"].lower()]
    return rows[skip : skip + limit]


@router.post("", status_code=201)
async def create_agent(data: AgentCreate, user: UserRecord = Depends(current_user)):
    payload = data.model_dump(exclude={"organization_id"})
    return ai_runtime.create_agent(payload, user.organization_id)


@router.get("/{agent_id}")
async def get_agent(agent_id: str, user: UserRecord = Depends(current_user)):
    agent = ai_runtime.get_agent(agent_id, user.organization_id)
    row = asdict(agent)
    row["provider"] = ai_runtime.providers.get(agent.provider_id).name if agent.provider_id in ai_runtime.providers else "Unknown"
    return row


@router.put("/{agent_id}")
async def update_agent(agent_id: str, data: AgentUpdate, user: UserRecord = Depends(current_user)):
    return ai_runtime.update_agent(agent_id, user.organization_id, data.model_dump(exclude_unset=True))


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, user: UserRecord = Depends(current_user)):
    ai_runtime.delete_agent(agent_id, user.organization_id)
    return {"message": "Agent deleted successfully"}


@router.post("/{agent_id}/execute", status_code=202)
async def execute_agent(
    agent_id: str,
    data: AgentExecutionRequest,
    background_tasks: BackgroundTasks,
    user: UserRecord = Depends(current_user),
):
    job = ai_runtime.create_job(agent_id, user.organization_id, data.prompt)
    background_tasks.add_task(ai_runtime.run_job, job.id)
    return asdict(job)


@router.get("/{agent_id}/tasks")
async def get_agent_tasks(agent_id: str, limit: int = 20, user: UserRecord = Depends(current_user)):
    ai_runtime.get_agent(agent_id, user.organization_id)
    return [row for row in ai_runtime.list_jobs(user.organization_id, limit=100) if row["agent_id"] == agent_id][:limit]


@router.get("/{agent_id}/knowledge")
async def get_agent_knowledge(agent_id: str, user: UserRecord = Depends(current_user)):
    agent = ai_runtime.get_agent(agent_id, user.organization_id)
    return {
        "agent_id": agent.id,
        "system_prompt": agent.system_prompt,
        "sources": [],
    }
