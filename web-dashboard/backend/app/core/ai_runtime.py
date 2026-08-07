"""In-memory AI runtime state for dashboard orchestration.

This module centralizes provider, agent, execution-job, and notification state so
API endpoints and websocket delivery share the same governed source of truth.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProviderRecord:
    id: str
    name: str
    type: str
    organization_id: str
    status: str = "connected"
    base_url: str | None = None
    api_key_hint: str = "configured"
    latency: int = 0
    cost_per_1k_tokens: float = 0.0
    usage_today: int = 0
    usage_limit: int = 0
    last_used: str | None = None
    created_at: str = field(default_factory=now_iso)
    enabled: bool = True


@dataclass
class AgentRecord:
    id: str
    name: str
    slug: str
    role: str
    department: str
    provider_id: str
    model: str
    organization_id: str
    workspace_id: str | None = None
    system_prompt: str | None = None
    status: str = "idle"
    temperature: float = 0.2
    tasks_completed: int = 0
    tasks_failed: int = 0
    performance: float = 100.0
    latency: int = 0
    cost: float = 0.0
    tokens_used: int = 0
    created_at: str = field(default_factory=now_iso)


@dataclass
class JobRecord:
    id: str
    agent_id: str
    organization_id: str
    prompt: str
    status: str = "queued"
    result: str | None = None
    tokens_used: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    error: str | None = None
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class NotificationRecord:
    id: str
    organization_id: str
    user_id: str | None
    type: str
    title: str
    message: str
    severity: str = "info"
    read: bool = False
    created_at: str = field(default_factory=now_iso)


class AIRealtimeHub:
    def __init__(self) -> None:
        self._clients: dict[str, set[Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, organization_id: str, websocket: Any) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.setdefault(organization_id, set()).add(websocket)

    async def disconnect(self, organization_id: str, websocket: Any) -> None:
        async with self._lock:
            clients = self._clients.get(organization_id)
            if clients:
                clients.discard(websocket)
                if not clients:
                    self._clients.pop(organization_id, None)

    async def publish(self, organization_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients.get(organization_id, set()))
        stale: list[Any] = []
        for client in clients:
            try:
                await client.send_json(event)
            except Exception:
                stale.append(client)
        for client in stale:
            await self.disconnect(organization_id, client)

    def connected_count(self, organization_id: str | None = None) -> int:
        if organization_id:
            return len(self._clients.get(organization_id, set()))
        return sum(len(clients) for clients in self._clients.values())


class AIRuntimeState:
    def __init__(self) -> None:
        self.providers: dict[str, ProviderRecord] = {}
        self.agents: dict[str, AgentRecord] = {}
        self.jobs: dict[str, JobRecord] = {}
        self.notifications: dict[str, NotificationRecord] = {}
        self.hub = AIRealtimeHub()
        self._bootstrap()

    def _bootstrap(self) -> None:
        provider = ProviderRecord(
            id="provider-openai",
            name="OpenAI",
            type="openai",
            organization_id="aionex-org",
            latency=145,
            cost_per_1k_tokens=0.03,
            usage_limit=10_000_000,
        )
        self.providers[provider.id] = provider
        agent = AgentRecord(
            id="agent-chief-engineer",
            name="Chief Engineer AI",
            slug="chief-engineer-ai",
            role="Chief Engineer",
            department="Engineering",
            provider_id=provider.id,
            model="gpt-4.1",
            organization_id="aionex-org",
            system_prompt="Review projects for readiness, safety, and architectural compliance.",
        )
        self.agents[agent.id] = agent

    def list_providers(self, organization_id: str) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.providers.values() if item.organization_id == organization_id]

    def create_provider(self, payload: dict[str, Any], organization_id: str) -> dict[str, Any]:
        provider_id = f"provider-{secrets.token_urlsafe(8)}"
        api_key = str(payload.pop("api_key", ""))
        provider = ProviderRecord(
            id=provider_id,
            organization_id=organization_id,
            api_key_hint=(f"***{api_key[-4:]}" if api_key else "not-configured"),
            **payload,
        )
        self.providers[provider_id] = provider
        return asdict(provider)

    def get_provider(self, provider_id: str, organization_id: str) -> ProviderRecord:
        provider = self.providers.get(provider_id)
        if provider is None or provider.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Provider not found")
        return provider

    def delete_provider(self, provider_id: str, organization_id: str) -> None:
        self.get_provider(provider_id, organization_id)
        if any(agent.provider_id == provider_id for agent in self.agents.values()):
            raise HTTPException(status_code=409, detail="Provider is assigned to active agents")
        self.providers.pop(provider_id, None)

    def list_agents(self, organization_id: str) -> list[dict[str, Any]]:
        result = []
        for agent in self.agents.values():
            if agent.organization_id != organization_id:
                continue
            row = asdict(agent)
            row["provider"] = self.providers.get(agent.provider_id).name if agent.provider_id in self.providers else "Unknown"
            result.append(row)
        return result

    def create_agent(self, payload: dict[str, Any], organization_id: str) -> dict[str, Any]:
        self.get_provider(payload["provider_id"], organization_id)
        agent_id = f"agent-{secrets.token_urlsafe(8)}"
        name = payload["name"].strip()
        slug = "-".join(name.lower().split())
        agent = AgentRecord(id=agent_id, slug=slug, organization_id=organization_id, **payload)
        self.agents[agent_id] = agent
        row = asdict(agent)
        row["provider"] = self.providers[agent.provider_id].name
        return row

    def get_agent(self, agent_id: str, organization_id: str) -> AgentRecord:
        agent = self.agents.get(agent_id)
        if agent is None or agent.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    def update_agent(self, agent_id: str, organization_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        agent = self.get_agent(agent_id, organization_id)
        for key, value in updates.items():
            if value is not None and hasattr(agent, key):
                setattr(agent, key, value)
        row = asdict(agent)
        row["provider"] = self.providers.get(agent.provider_id).name if agent.provider_id in self.providers else "Unknown"
        return row

    def delete_agent(self, agent_id: str, organization_id: str) -> None:
        self.get_agent(agent_id, organization_id)
        self.agents.pop(agent_id, None)

    def create_job(self, agent_id: str, organization_id: str, prompt: str) -> JobRecord:
        self.get_agent(agent_id, organization_id)
        job = JobRecord(
            id=f"job-{secrets.token_urlsafe(10)}",
            agent_id=agent_id,
            organization_id=organization_id,
            prompt=prompt,
        )
        self.jobs[job.id] = job
        return job

    async def run_job(self, job_id: str) -> None:
        job = self.jobs[job_id]
        agent = self.agents[job.agent_id]
        job.status = "running"
        job.started_at = now_iso()
        agent.status = "running"
        await self.hub.publish(job.organization_id, {"type": "job.updated", "job": asdict(job)})
        try:
            await asyncio.sleep(0)
            job.result = f"Execution accepted by {agent.name}: {job.prompt[:240]}"
            job.tokens_used = max(1, len(job.prompt.split()) * 2)
            job.cost = round(job.tokens_used * 0.00003, 6)
            job.latency_ms = 1
            job.status = "completed"
            job.completed_at = now_iso()
            agent.tasks_completed += 1
            agent.tokens_used += job.tokens_used
            agent.cost = round(agent.cost + job.cost, 6)
            agent.latency = job.latency_ms
            agent.status = "idle"
            self.providers[agent.provider_id].usage_today += job.tokens_used
            self.providers[agent.provider_id].last_used = now_iso()
            notification = self.add_notification(
                organization_id=job.organization_id,
                user_id=None,
                type="job.completed",
                title="AI job completed",
                message=f"{agent.name} completed job {job.id}",
                severity="success",
            )
            await self.hub.publish(job.organization_id, {"type": "job.updated", "job": asdict(job)})
            await self.hub.publish(job.organization_id, {"type": "notification.created", "notification": notification})
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.completed_at = now_iso()
            agent.tasks_failed += 1
            agent.status = "error"
            await self.hub.publish(job.organization_id, {"type": "job.updated", "job": asdict(job)})

    def list_jobs(self, organization_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = [asdict(job) for job in self.jobs.values() if job.organization_id == organization_id]
        rows.sort(key=lambda item: item["created_at"], reverse=True)
        return rows[:limit]

    def add_notification(self, organization_id: str, user_id: str | None, type: str, title: str, message: str, severity: str = "info") -> dict[str, Any]:
        record = NotificationRecord(
            id=f"notification-{secrets.token_urlsafe(8)}",
            organization_id=organization_id,
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            severity=severity,
        )
        self.notifications[record.id] = record
        return asdict(record)

    def list_notifications(self, organization_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for item in self.notifications.values():
            if item.organization_id != organization_id:
                continue
            if item.user_id not in (None, user_id):
                continue
            rows.append(asdict(item))
        rows.sort(key=lambda item: item["created_at"], reverse=True)
        return rows

    def mark_notification(self, notification_id: str, organization_id: str, read: bool = True) -> dict[str, Any]:
        item = self.notifications.get(notification_id)
        if item is None or item.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Notification not found")
        item.read = read
        return asdict(item)


ai_runtime = AIRuntimeState()

# Phase 29J final provider catalog helpers.
FINAL_SUPPORTED_PROVIDER_TYPES = (
    "openai", "anthropic", "gemini", "openrouter", "ollama", "mistral",
    "cohere", "xai", "deepseek", "groq", "together", "fireworks",
    "huggingface", "azure_openai", "aws_bedrock", "tripo3d", "meshy",
)


def provider_models(provider_type: str) -> list[dict[str, object]]:
    from aios.providers.adapters.catalog import default_providers

    provider = next((item for item in default_providers() if item.name == provider_type), None)
    if provider is None:
        return []
    return [
        {
            "provider": cap.provider,
            "model": cap.model,
            "tasks": sorted(cap.tasks),
            "languages": sorted(cap.languages),
            "supports_tools": cap.supports_tools,
            "supports_vision": cap.supports_vision,
            "supports_audio": cap.supports_audio,
            "local": cap.local,
            "max_context_tokens": cap.max_context_tokens,
            "quality_score": cap.quality_score,
            "latency_score": cap.latency_score,
            "privacy_score": cap.privacy_score,
            "input_cost_per_million": cap.input_cost_per_million,
            "output_cost_per_million": cap.output_cost_per_million,
        }
        for cap in provider.capabilities()
    ]
