"""Durable AI provider and agent runtime for Phase 29J.

Provider/agent/job state is stored in PostgreSQL. Realtime websocket connections remain
process-local by design, but no business state depends on process memory.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import boto3  # type: ignore[import-untyped]
import httpx
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.db.models import AIAgent, AIProvider, AuditEvent, Job, User, uuid_str
from app.services import communications
from app.services.provider_credit_alerts import notify_provider_billing_failure
from app.services.project_execution_routing_durable import usd_to_microusd

logger = get_logger(__name__)

SUPPORTED_PROVIDER_TYPES = (
    "openai",
    "anthropic",
    "gemini",
    "openrouter",
    "ollama",
    "mistral",
    "cohere",
    "xai",
    "deepseek",
    "groq",
    "together",
    "fireworks",
    "huggingface",
    "azure_openai",
    "aws_bedrock",
    "tripo3d",
    "meshy",
)

DEDICATED_3D_PROVIDER_TYPES = frozenset({"tripo3d", "meshy"})
AGENT_RUNTIME_PROVIDER_TYPES = frozenset(SUPPORTED_PROVIDER_TYPES) - DEDICATED_3D_PROVIDER_TYPES

_SERVER_CREDENTIALS: dict[str, tuple[str, str | None]] = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com"),
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com"),
    "gemini": ("GOOGLE_API_KEY", "https://generativelanguage.googleapis.com"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai"),
    "cohere": ("COHERE_API_KEY", "https://api.cohere.com"),
    "xai": ("XAI_API_KEY", "https://api.x.ai"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai"),
    "together": ("TOGETHER_API_KEY", "https://api.together.ai"),
    "fireworks": ("FIREWORKS_API_KEY", "https://api.fireworks.ai/inference"),
    "huggingface": ("HUGGINGFACE_API_KEY", "https://router.huggingface.co"),
    "azure_openai": ("AZURE_OPENAI_API_KEY", None),
}

_OPENAI_COMPATIBLE_PROVIDER_TYPES = frozenset({
    "mistral", "xai", "deepseek", "groq", "together", "fireworks", "huggingface"
})

_OFFICIAL_PROVIDER_HOSTS = {
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
    "gemini": "generativelanguage.googleapis.com",
    "openrouter": "openrouter.ai",
    "mistral": "api.mistral.ai",
    "cohere": "api.cohere.com",
    "xai": "api.x.ai",
    "deepseek": "api.deepseek.com",
    "groq": "api.groq.com",
    "together": "api.together.ai",
    "fireworks": "api.fireworks.ai",
    "huggingface": "router.huggingface.co",
}

_PROVIDER_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
    "mistral": "Mistral",
    "cohere": "Cohere",
    "xai": "xAI",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "together": "Together AI",
    "fireworks": "Fireworks AI",
    "huggingface": "Hugging Face",
    "azure_openai": "Azure OpenAI",
    "aws_bedrock": "AWS Bedrock",
    "tripo3d": "Tripo3D",
    "meshy": "Meshy",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_provider_secret(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Provider API key is required")
    return "fernet:v1:" + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_provider_secret(value: str | None) -> str | None:
    if not value:
        return None
    token = value.removeprefix("fernet:v1:")
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Provider credential cannot be decrypted") from exc


def _server_credential(provider_type: str) -> str | None:
    spec = _SERVER_CREDENTIALS.get(provider_type)
    if spec is None:
        return None
    value = getattr(settings, spec[0], None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def provider_credential(provider: AIProvider) -> str | None:
    stored = decrypt_provider_secret(provider.encrypted_api_key)
    if stored:
        return stored
    if (provider.config or {}).get("credential_source") == "environment":
        return _server_credential(provider.type)
    return None


def _default_base_url(provider_type: str) -> str | None:
    if provider_type == "azure_openai":
        endpoint = str(settings.AZURE_OPENAI_ENDPOINT or "").strip().rstrip("/")
        return endpoint or None
    spec = _SERVER_CREDENTIALS.get(provider_type)
    return spec[1] if spec else None


def _aws_bedrock_configured() -> bool:
    return bool(
        str(settings.AWS_ACCESS_KEY_ID or "").strip()
        and str(settings.AWS_SECRET_ACCESS_KEY or "").strip()
        and str(settings.AWS_BEDROCK_REGION or "").strip()
    )


def provider_runtime_contract(provider_type: str) -> dict[str, str]:
    if provider_type in DEDICATED_3D_PROVIDER_TYPES:
        return {
            "runtime_mode": "catalog_only_3d_connector",
            "protocol": "not-agent-executable",
            "reason": "External Tripo3D/Meshy catalog entries are not agent-runtime providers; production 3D execution uses the licensed Hunyuan3D/TripoSR RunPod pipeline.",
        }
    if provider_type == "ollama":
        return {"runtime_mode": "agent", "protocol": "ollama-chat", "reason": "Local Ollama chat runtime."}
    if provider_type == "openai":
        protocol = "openai-responses"
    elif provider_type == "anthropic":
        protocol = "anthropic-messages"
    elif provider_type == "gemini":
        protocol = "gemini-generate-content"
    elif provider_type == "openrouter":
        protocol = "openrouter-chat-completions"
    elif provider_type == "cohere":
        protocol = "cohere-v2-chat"
    elif provider_type == "azure_openai":
        protocol = "azure-openai-v1-chat"
    elif provider_type == "aws_bedrock":
        protocol = "aws-bedrock-converse"
    else:
        protocol = "openai-compatible-chat"
    return {"runtime_mode": "agent", "protocol": protocol, "reason": "Executable through the durable AI agent runtime when configured."}


def _chat_api_root(provider_type: str, base: str) -> str:
    if provider_type == "openrouter":
        return f"{base}/api/v1"
    if provider_type == "azure_openai":
        return f"{base}/openai/v1"
    return f"{base}/v1"


def validate_provider_base_url(provider_type: str, base_url: str | None) -> str | None:
    raw = (base_url or _default_base_url(provider_type) or "").strip().rstrip("/")
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail="Provider base URL contains unsupported components")
    if provider_type == "ollama":
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HTTPException(status_code=422, detail="Ollama base URL is invalid")
        if parsed.path not in {"", "/"}:
            raise HTTPException(status_code=422, detail="Ollama base URL must not include an API path")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            if parsed.hostname == "ollama":
                if parsed.port not in {None, 11434}:
                    raise HTTPException(status_code=422, detail="Internal Ollama service must use port 11434")
            elif parsed.hostname not in {"localhost", "host.docker.internal"}:
                raise HTTPException(status_code=422, detail="Ollama must use an explicit local runtime address")
        else:
            if not (address.is_loopback or address.is_private):
                raise HTTPException(status_code=422, detail="Ollama must use a local/private runtime address")
        return raw
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Cloud provider base URL must use HTTPS")
    official = _OFFICIAL_PROVIDER_HOSTS.get(provider_type)
    if official and parsed.hostname != official:
        raise HTTPException(status_code=422, detail="Built-in provider must use its official API host")
    if provider_type == "azure_openai" and not (
        parsed.hostname.endswith(".openai.azure.com")
        or parsed.hostname.endswith(".services.ai.azure.com")
        or parsed.hostname.endswith(".cognitiveservices.azure.com")
    ):
        raise HTTPException(status_code=422, detail="Azure OpenAI endpoint must use an Azure AI service host")
    return raw


def provider_configured(provider: AIProvider) -> bool:
    if provider.type == "ollama":
        return bool(provider.base_url)
    if provider.type == "aws_bedrock":
        return (provider.config or {}).get("credential_source") == "environment" and _aws_bedrock_configured()
    if provider.type == "azure_openai":
        return provider_credential(provider) is not None and validate_provider_base_url(provider.type, provider.base_url) is not None
    if provider.type in DEDICATED_3D_PROVIDER_TYPES:
        return False
    return provider_credential(provider) is not None


def provider_enabled(provider: AIProvider) -> bool:
    return provider.status not in {"disabled", "removed"} and bool((provider.config or {}).get("enabled", True))


def _provider_metrics(provider: AIProvider) -> dict[str, Any]:
    config = provider.config or {}
    return {
        "latency": int(config.get("latency_ms", 0) or 0),
        "cost_per_1k_tokens": float(config.get("cost_per_1k_tokens", 0.0) or 0.0),
        "usage_today": int(config.get("usage_today", 0) or 0),
        "usage_limit": int(config.get("usage_limit", 0) or 0),
        "last_used": config.get("last_used"),
    }


def provider_snapshot(provider: AIProvider) -> dict[str, Any]:
    metrics = _provider_metrics(provider)
    configured = provider_configured(provider)
    enabled = provider_enabled(provider)
    return {
        "id": provider.id,
        "organization_id": provider.organization_id,
        "name": provider.name,
        "type": provider.type,
        "status": provider.status if configured else "unconfigured",
        "base_url": provider.base_url,
        "api_key_hint": "configured" if configured else "not-configured",
        "configured": configured,
        "enabled": enabled,
        "managed_by": "server" if (provider.config or {}).get("credential_source") == "environment" else "database",
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        **metrics,
    }


def agent_snapshot(agent: AIAgent, provider: AIProvider | None = None) -> dict[str, Any]:
    metrics = agent.metrics or {}
    completed = int(metrics.get("tasks_completed", 0) or 0)
    failed = int(metrics.get("tasks_failed", 0) or 0)
    attempted = completed + failed
    performance = round((completed / attempted) * 100, 2) if attempted else 100.0
    return {
        "id": agent.id,
        "organization_id": agent.organization_id,
        "workspace_id": agent.workspace_id,
        "name": agent.name,
        "slug": agent.slug,
        "role": agent.role,
        "department": agent.department,
        "provider_id": agent.provider_id,
        "provider": provider.name if provider else "Unknown",
        "model": agent.model,
        "status": agent.status,
        "system_prompt": agent.system_prompt,
        "temperature": agent.temperature,
        "tasks_completed": completed,
        "tasks_failed": failed,
        "performance": performance,
        "latency": int(metrics.get("latency_ms", 0) or 0),
        "cost": float(metrics.get("cost", 0.0) or 0.0),
        "tokens_used": int(metrics.get("tokens_used", 0) or 0),
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
    }


def job_snapshot(job: Job) -> dict[str, Any]:
    payload = job.payload or {}
    result = job.result or {}
    usage = result.get("usage") or {}
    return {
        "id": job.id,
        "agent_id": job.agent_id,
        "organization_id": job.organization_id,
        "prompt": payload.get("prompt", ""),
        "status": job.status,
        "result": result.get("text"),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "tokens_used": int(usage.get("total_tokens", 0) or 0),
        "cost": float(result.get("cost", 0.0) or 0.0),
        "latency_ms": float(result.get("latency_ms", 0.0) or 0.0),
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.finished_at.isoformat() if job.finished_at else None,
    }


async def ensure_environment_providers(session: AsyncSession, organization_id: str) -> None:
    configured_specs: list[tuple[str, str | None]] = []
    for provider_type, (setting_name, default_url) in _SERVER_CREDENTIALS.items():
        if not str(getattr(settings, setting_name, None) or "").strip():
            continue
        resolved_url = _default_base_url(provider_type) or default_url
        if provider_type == "azure_openai" and not resolved_url:
            continue
        configured_specs.append((provider_type, resolved_url))
    if _aws_bedrock_configured():
        configured_specs.append(("aws_bedrock", None))

    for provider_type, resolved_url in configured_specs:
        existing = await session.scalar(
            select(AIProvider).where(
                AIProvider.organization_id == organization_id,
                AIProvider.type == provider_type,
                AIProvider.config["credential_source"].as_string() == "environment",
            )
        )
        if existing is not None:
            if resolved_url and existing.base_url != resolved_url:
                existing.base_url = resolved_url
            continue
        session.add(
            AIProvider(
                organization_id=organization_id,
                name=_PROVIDER_NAMES[provider_type],
                type=provider_type,
                status="configured",
                encrypted_api_key=None,
                base_url=resolved_url,
                config={
                    "credential_source": "environment",
                    "enabled": True,
                    "usage_today": 0,
                    "usage_limit": 0,
                    "latency_ms": 0,
                    "cost_per_1k_tokens": 0.0,
                },
            )
        )
    await session.flush()


async def list_providers(session: AsyncSession, organization_id: str, *, include_environment: bool = False) -> list[dict[str, Any]]:
    if include_environment:
        await ensure_environment_providers(session, organization_id)
        await session.commit()
    rows = list(
        (
            await session.scalars(
                select(AIProvider)
                .where(AIProvider.organization_id == organization_id)
                .order_by(AIProvider.created_at.asc(), AIProvider.name.asc())
            )
        ).all()
    )
    return [provider_snapshot(row) for row in rows]


async def get_provider(session: AsyncSession, provider_id: str, organization_id: str, *, lock: bool = False) -> AIProvider:
    statement = select(AIProvider).where(
        AIProvider.id == provider_id,
        AIProvider.organization_id == organization_id,
    )
    if lock:
        statement = statement.with_for_update()
    provider = await session.scalar(statement)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


async def create_provider(session: AsyncSession, payload: dict[str, Any], organization_id: str, actor_id: str) -> dict[str, Any]:
    provider_type = str(payload.get("type") or "").strip().lower()
    if provider_type not in SUPPORTED_PROVIDER_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported provider type")
    if provider_type in DEDICATED_3D_PROVIDER_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Tripo3D/Meshy catalog connectors are not executable through the AI agent runtime; production 3D uses the Hunyuan3D/TripoSR pipeline",
        )
    api_key = str(payload.get("api_key", "") or "").strip()
    base_url = validate_provider_base_url(provider_type, payload.get("base_url"))
    if provider_type == "aws_bedrock":
        if api_key or payload.get("base_url"):
            raise HTTPException(status_code=422, detail="AWS Bedrock uses the server AWS credential chain and region, not a single API key or base URL")
        if not _aws_bedrock_configured():
            raise HTTPException(status_code=422, detail="AWS Bedrock server credentials and region are not configured")
    elif provider_type != "ollama" and not api_key:
        raise HTTPException(status_code=422, detail="Provider credential is required")
    if provider_type == "ollama" and not base_url:
        raise HTTPException(status_code=422, detail="Ollama local runtime URL is required")
    if provider_type == "azure_openai" and not base_url:
        raise HTTPException(status_code=422, detail="Azure OpenAI endpoint is required")
    if provider_type not in {*_SERVER_CREDENTIALS, "ollama", "aws_bedrock"} and not base_url:
        raise HTTPException(status_code=422, detail="Provider HTTPS base URL is required")
    provider = AIProvider(
        id=uuid_str(),
        organization_id=organization_id,
        name=str(payload.get("name") or _PROVIDER_NAMES.get(provider_type, provider_type)).strip(),
        type=provider_type,
        status="configured",
        encrypted_api_key=encrypt_provider_secret(api_key) if api_key else None,
        base_url=base_url,
        config={
            "credential_source": "environment" if provider_type == "aws_bedrock" else ("database" if api_key else "environment"),
            "enabled": True,
            "cost_per_1k_tokens": float(payload.get("cost_per_1k_tokens", 0.0) or 0.0),
            "usage_limit": int(payload.get("usage_limit", 0) or 0),
            "usage_today": 0,
            "latency_ms": 0,
        },
    )
    session.add(provider)
    await session.flush()
    session.add(AuditEvent(organization_id=organization_id, user_id=actor_id, action="ai.provider.created", resource_type="ai_provider", resource_id=provider.id, details={"type": provider.type, "credential_source": provider.config.get("credential_source")}))
    await session.commit()
    await session.refresh(provider)
    return provider_snapshot(provider)


async def delete_provider(session: AsyncSession, provider_id: str, organization_id: str, actor_id: str) -> None:
    provider = await get_provider(session, provider_id, organization_id, lock=True)
    if (provider.config or {}).get("credential_source") == "environment":
        raise HTTPException(
            status_code=409,
            detail="Server-managed provider cannot be deleted through the API; remove or rotate its protected server credential instead",
        )
    assigned = await session.scalar(select(AIAgent.id).where(AIAgent.provider_id == provider.id).limit(1))
    if assigned is not None:
        raise HTTPException(status_code=409, detail="Provider is assigned to an agent")
    session.add(AuditEvent(organization_id=organization_id, user_id=actor_id, action="ai.provider.deleted", resource_type="ai_provider", resource_id=provider.id, details={"type": provider.type}))
    await session.delete(provider)
    await session.commit()


async def list_agents(session: AsyncSession, organization_id: str, *, status: str | None = None, provider_name: str | None = None, role: str | None = None, search: str | None = None, skip: int = 0, limit: int = 20) -> list[dict[str, Any]]:
    statement = (
        select(AIAgent, AIProvider)
        .join(AIProvider, AIProvider.id == AIAgent.provider_id)
        .where(AIAgent.organization_id == organization_id)
    )
    if status:
        statement = statement.where(AIAgent.status == status)
    if provider_name:
        statement = statement.where(AIProvider.name.ilike(provider_name))
    if role:
        statement = statement.where(AIAgent.role.ilike(role))
    if search:
        needle = f"%{search.strip()}%"
        statement = statement.where((AIAgent.name.ilike(needle)) | (AIAgent.role.ilike(needle)))
    rows = (await session.execute(statement.order_by(AIAgent.created_at.desc()).offset(skip).limit(limit))).all()
    return [agent_snapshot(agent, provider) for agent, provider in rows]


async def get_agent(session: AsyncSession, agent_id: str, organization_id: str, *, lock: bool = False) -> tuple[AIAgent, AIProvider]:
    statement = (
        select(AIAgent, AIProvider)
        .join(AIProvider, AIProvider.id == AIAgent.provider_id)
        .where(AIAgent.id == agent_id, AIAgent.organization_id == organization_id)
    )
    if lock:
        statement = statement.with_for_update(of=AIAgent)
    row = (await session.execute(statement)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return row[0], row[1]


async def create_agent(session: AsyncSession, payload: dict[str, Any], organization_id: str, actor_id: str) -> dict[str, Any]:
    provider = await get_provider(session, str(payload.get("provider_id")), organization_id)
    if provider.type in DEDICATED_3D_PROVIDER_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Tripo3D/Meshy catalog connectors are not executable through the AI agent runtime; production 3D uses the Hunyuan3D/TripoSR pipeline",
        )
    if not provider_configured(provider) or not provider_enabled(provider):
        raise HTTPException(status_code=409, detail="Provider is not configured and enabled")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Agent name is required")
    model = str(payload.get("model") or "").strip()
    if not model or model == "default":
        raise HTTPException(status_code=422, detail="An explicit provider model ID is required")
    agent = AIAgent(
        id=uuid_str(),
        organization_id=organization_id,
        workspace_id=payload.get("workspace_id"),
        provider_id=provider.id,
        name=name,
        slug="-".join(name.lower().split())[:200],
        role=str(payload.get("role") or "Agent").strip(),
        department=str(payload.get("department") or "AI").strip(),
        model=model,
        status="idle",
        system_prompt=(str(payload.get("system_prompt") or "").strip() or None),
        temperature=float(payload.get("temperature", 0.2) or 0.2),
        metrics={"tasks_completed": 0, "tasks_failed": 0, "latency_ms": 0, "cost": 0.0, "tokens_used": 0},
    )
    session.add(agent)
    await session.flush()
    session.add(AuditEvent(organization_id=organization_id, user_id=actor_id, action="ai.agent.created", resource_type="ai_agent", resource_id=agent.id, details={"provider_id": provider.id, "model": model}))
    await session.commit()
    await session.refresh(agent)
    return agent_snapshot(agent, provider)


async def update_agent(session: AsyncSession, agent_id: str, organization_id: str, updates: dict[str, Any], actor_id: str) -> dict[str, Any]:
    agent, provider = await get_agent(session, agent_id, organization_id, lock=True)
    allowed = {"name", "role", "status", "system_prompt", "temperature", "model"}
    for key, value in updates.items():
        if key not in allowed or value is None:
            continue
        if key == "status" and value not in {"idle", "paused", "disabled"}:
            raise HTTPException(status_code=422, detail="Unsupported agent status")
        setattr(agent, key, value)
    if "name" in updates and updates.get("name"):
        agent.slug = "-".join(str(agent.name).lower().split())[:200]
    session.add(AuditEvent(organization_id=organization_id, user_id=actor_id, action="ai.agent.updated", resource_type="ai_agent", resource_id=agent.id, details={"fields": sorted(k for k in updates if k in allowed)}))
    await session.commit()
    await session.refresh(agent)
    return agent_snapshot(agent, provider)


async def delete_agent(session: AsyncSession, agent_id: str, organization_id: str, actor_id: str) -> None:
    agent, _ = await get_agent(session, agent_id, organization_id, lock=True)
    active_job = await session.scalar(select(Job.id).where(Job.agent_id == agent.id, Job.status.in_({"queued", "running"})).limit(1))
    if active_job is not None:
        raise HTTPException(status_code=409, detail="Agent has an active execution")
    session.add(AuditEvent(organization_id=organization_id, user_id=actor_id, action="ai.agent.deleted", resource_type="ai_agent", resource_id=agent.id, details={"name": agent.name}))
    await session.delete(agent)
    await session.commit()


async def create_job(session: AsyncSession, agent_id: str, organization_id: str, prompt: str, actor_id: str) -> Job:
    agent, provider = await get_agent(session, agent_id, organization_id, lock=True)
    if agent.status in {"paused", "disabled"}:
        raise HTTPException(status_code=409, detail="Agent is not available for execution")
    if not provider_configured(provider) or not provider_enabled(provider):
        raise HTTPException(status_code=409, detail="Provider is not configured and enabled")
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise HTTPException(status_code=422, detail="Prompt is required")
    job = Job(id=uuid_str(), organization_id=organization_id, agent_id=agent.id, type="ai_agent_execution", status="queued", payload={"prompt": clean_prompt, "requested_by_id": actor_id}, result={})
    session.add(job)
    session.add(AuditEvent(organization_id=organization_id, user_id=actor_id, action="ai.job.queued", resource_type="ai_job", resource_id=job.id, details={"agent_id": agent.id, "provider_id": provider.id, "model": agent.model}))
    await session.commit()
    await session.refresh(job)
    return job


def _usage_total(usage: dict[str, Any]) -> int:
    return int(usage.get("total_tokens") or usage.get("totalTokenCount") or (int(usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("promptTokenCount") or 0) + int(usage.get("output_tokens") or usage.get("completion_tokens") or usage.get("candidatesTokenCount") or 0)))


def _openai_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return str(payload["output_text"])
    pieces: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                pieces.append(part["text"])
    return "".join(pieces).strip()


async def _request_json(method: str, url: str, *, headers: dict[str, str], json_body: dict[str, Any] | None = None, timeout: float = 30.0, allow_array: bool = False) -> tuple[Any, float]:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0), follow_redirects=False) as client:
            response = await client.request(method, url, headers=headers, json=json_body)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(status_code=503, detail=f"Provider connection failed ({type(exc).__name__})") from exc
    elapsed_ms = (time.monotonic() - started) * 1000
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Provider returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Provider returned invalid JSON") from exc
    if not isinstance(payload, dict) and not (allow_array and isinstance(payload, list)):
        raise HTTPException(status_code=502, detail="Provider returned an invalid response object")
    return payload, elapsed_ms


async def provider_health_probe(provider: AIProvider) -> dict[str, Any]:
    if provider.type in DEDICATED_3D_PROVIDER_TYPES:
        return {
            "status": "catalog_only",
            "latency_ms": 0,
            "message": "Tripo3D/Meshy are catalog connectors only; production 3D health is owned by the Hunyuan3D/TripoSR RunPod pipeline",
        }
    if not provider_enabled(provider):
        return {"status": "disabled", "latency_ms": 0, "message": "Provider is disabled"}
    if provider.type == "aws_bedrock":
        if not provider_configured(provider):
            return {"status": "unconfigured", "latency_ms": 0, "message": "AWS Bedrock credentials or region are not configured"}
        return {"status": "configured", "latency_ms": 0, "message": "AWS Bedrock credential chain and region are configured; execution is the authoritative live verification"}
    base = validate_provider_base_url(provider.type, provider.base_url)
    credential = provider_credential(provider)
    if provider.type != "ollama" and not credential:
        return {"status": "unconfigured", "latency_ms": 0, "message": "Provider credential is not configured"}
    if not base:
        return {"status": "unconfigured", "latency_ms": 0, "message": "Provider endpoint is not configured"}
    if provider.type == "openai":
        _, latency = await _request_json("GET", f"{base}/v1/models", headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"})
    elif provider.type == "gemini":
        _, latency = await _request_json("GET", f"{base}/v1beta/models", headers={"x-goog-api-key": str(credential), "Accept": "application/json"})
    elif provider.type == "ollama":
        _, latency = await _request_json("GET", f"{base}/api/tags", headers={"Accept": "application/json"})
    elif provider.type in {"anthropic", "cohere"}:
        return {"status": "configured", "latency_ms": 0, "message": f"{_PROVIDER_NAMES[provider.type]} credential configured; execution is the authoritative live verification"}
    elif provider.type == "azure_openai":
        _, latency = await _request_json("GET", f"{_chat_api_root(provider.type, base)}/models", headers={"api-key": str(credential), "Accept": "application/json"})
    elif provider.type == "together":
        # Together's authenticated model inventory is a top-level JSON array.
        _, latency = await _request_json(
            "GET",
            f"{_chat_api_root(provider.type, base)}/models",
            headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"},
            allow_array=True,
        )
    else:
        _, latency = await _request_json("GET", f"{_chat_api_root(provider.type, base)}/models", headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"})
    return {"status": "success", "latency_ms": round(latency, 2), "message": "Provider endpoint verified"}


def _execute_bedrock_sync(agent: AIAgent, prompt: str, max_tokens: int) -> dict[str, Any]:
    region = str(settings.AWS_BEDROCK_REGION or "").strip()
    if not _aws_bedrock_configured() or not region:
        raise HTTPException(status_code=503, detail="AWS Bedrock credentials or region are not configured")
    kwargs: dict[str, Any] = {
        "region_name": region,
        "aws_access_key_id": str(settings.AWS_ACCESS_KEY_ID),
        "aws_secret_access_key": str(settings.AWS_SECRET_ACCESS_KEY),
    }
    if settings.AWS_SESSION_TOKEN:
        kwargs["aws_session_token"] = str(settings.AWS_SESSION_TOKEN)
    started = time.monotonic()
    try:
        client = boto3.client("bedrock-runtime", **kwargs)
        request: dict[str, Any] = {
            "modelId": agent.model,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": float(agent.temperature)},
        }
        if agent.system_prompt:
            request["system"] = [{"text": agent.system_prompt}]
        payload = client.converse(**request)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=502, detail=f"AWS Bedrock request failed ({type(exc).__name__})") from exc
    elapsed_ms = (time.monotonic() - started) * 1000
    output = payload.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []
    text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict)).strip()
    raw_usage = payload.get("usage") or {}
    usage = {
        "input_tokens": int(raw_usage.get("inputTokens", 0) or 0),
        "output_tokens": int(raw_usage.get("outputTokens", 0) or 0),
        "total_tokens": int(raw_usage.get("totalTokens", 0) or 0),
    }
    if not usage["total_tokens"]:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    response_metadata = payload.get("ResponseMetadata") or {}
    return {
        "text": text,
        "usage": usage,
        "model": agent.model,
        "response_id": response_metadata.get("RequestId"),
        "latency_ms": elapsed_ms,
    }


async def _execute_provider(provider: AIProvider, agent: AIAgent, prompt: str) -> dict[str, Any]:
    if provider.type in DEDICATED_3D_PROVIDER_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Tripo3D/Meshy catalog connectors are not executable through the AI agent runtime; production 3D uses the Hunyuan3D/TripoSR pipeline",
        )
    system_prompt = agent.system_prompt or ""
    max_tokens = int((provider.config or {}).get("max_output_tokens", 1024) or 1024)
    max_tokens = max(1, min(max_tokens, 4096))
    if provider.type == "aws_bedrock":
        if not provider_configured(provider):
            raise HTTPException(status_code=503, detail="AWS Bedrock credentials or region are not configured")
        bedrock = await asyncio.to_thread(_execute_bedrock_sync, agent, prompt, max_tokens)
        text = str(bedrock["text"]).strip()
        usage = dict(bedrock["usage"])
        model = str(bedrock["model"])
        response_id = bedrock.get("response_id")
        latency = float(bedrock["latency_ms"])
    else:
        base = validate_provider_base_url(provider.type, provider.base_url)
        credential = provider_credential(provider)
        if provider.type != "ollama" and not credential:
            raise HTTPException(status_code=503, detail="Provider credential is not configured")
        if not base:
            raise HTTPException(status_code=503, detail="Provider endpoint is not configured")
        if provider.type == "openai":
            body: dict[str, Any] = {"model": agent.model, "input": prompt, "max_output_tokens": max_tokens, "store": False}
            if system_prompt:
                body["instructions"] = system_prompt
            payload, latency = await _request_json("POST", f"{base}/v1/responses", headers={"Authorization": f"Bearer {credential}", "Content-Type": "application/json", "Accept": "application/json"}, json_body=body, timeout=60)
            text = _openai_text(payload)
            usage = payload.get("usage") or {}
            model = str(payload.get("model") or agent.model)
            response_id = payload.get("id")
        elif provider.type == "anthropic":
            body = {"model": agent.model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
            if system_prompt:
                body["system"] = system_prompt
            payload, latency = await _request_json("POST", f"{base}/v1/messages", headers={"x-api-key": str(credential), "anthropic-version": "2023-06-01", "Content-Type": "application/json", "Accept": "application/json"}, json_body=body, timeout=60)
            text = "".join(str(part.get("text", "")) for part in payload.get("content") or [] if isinstance(part, dict) and part.get("type") == "text").strip()
            raw_usage = payload.get("usage") or {}
            usage = {"input_tokens": int(raw_usage.get("input_tokens", 0) or 0), "output_tokens": int(raw_usage.get("output_tokens", 0) or 0)}
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            model = str(payload.get("model") or agent.model)
            response_id = payload.get("id")
        elif provider.type == "gemini":
            body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_tokens, "temperature": agent.temperature}}
            if system_prompt:
                body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
            model_path = agent.model if agent.model.startswith("models/") else f"models/{agent.model}"
            payload, latency = await _request_json("POST", f"{base}/v1beta/{model_path}:generateContent", headers={"x-goog-api-key": str(credential), "Content-Type": "application/json", "Accept": "application/json"}, json_body=body, timeout=60)
            candidates = payload.get("candidates") or []
            parts = (((candidates[0] if candidates else {}).get("content") or {}).get("parts") or []) if isinstance(candidates, list) else []
            text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
            meta = payload.get("usageMetadata") or {}
            usage = {"input_tokens": int(meta.get("promptTokenCount", 0) or 0), "output_tokens": int(meta.get("candidatesTokenCount", 0) or 0), "total_tokens": int(meta.get("totalTokenCount", 0) or 0)}
            model = agent.model
            response_id = payload.get("responseId")
        elif provider.type == "ollama":
            body = {"model": agent.model, "stream": False, "messages": ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": prompt}], "options": {"temperature": agent.temperature, "num_predict": max_tokens}}
            payload, latency = await _request_json("POST", f"{base}/api/chat", headers={"Content-Type": "application/json"}, json_body=body, timeout=120)
            text = str((payload.get("message") or {}).get("content") or "").strip()
            usage = {"input_tokens": int(payload.get("prompt_eval_count", 0) or 0), "output_tokens": int(payload.get("eval_count", 0) or 0)}
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            model = str(payload.get("model") or agent.model)
            response_id = None
        elif provider.type == "cohere":
            messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": prompt}]
            body = {"model": agent.model, "messages": messages, "max_tokens": max_tokens, "temperature": agent.temperature, "stream": False}
            payload, latency = await _request_json("POST", f"{base}/v2/chat", headers={"Authorization": f"Bearer {credential}", "Content-Type": "application/json", "Accept": "application/json"}, json_body=body, timeout=60)
            message = payload.get("message") or {}
            content = message.get("content") or []
            text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text").strip()
            raw_usage = payload.get("usage") or {}
            token_usage = raw_usage.get("tokens") or raw_usage.get("billed_units") or {}
            usage = {"input_tokens": int(token_usage.get("input_tokens", 0) or 0), "output_tokens": int(token_usage.get("output_tokens", 0) or 0)}
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            model = agent.model
            response_id = payload.get("id")
        elif provider.type == "azure_openai":
            messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": prompt}]
            body = {"model": agent.model, "messages": messages, "max_tokens": max_tokens, "temperature": agent.temperature}
            payload, latency = await _request_json("POST", f"{_chat_api_root(provider.type, base)}/chat/completions", headers={"api-key": str(credential), "Content-Type": "application/json", "Accept": "application/json"}, json_body=body, timeout=60)
            choices = payload.get("choices") or []
            text = str((((choices[0] if choices else {}).get("message") or {}).get("content")) or "").strip()
            usage = payload.get("usage") or {}
            model = str(payload.get("model") or agent.model)
            response_id = payload.get("id") or payload.get("request_id")
        else:
            messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": prompt}]
            body = {"model": agent.model, "messages": messages, "max_tokens": max_tokens, "temperature": agent.temperature}
            payload, latency = await _request_json("POST", f"{_chat_api_root(provider.type, base)}/chat/completions", headers={"Authorization": f"Bearer {credential}", "Content-Type": "application/json", "Accept": "application/json"}, json_body=body, timeout=60)
            choices = payload.get("choices") or []
            text = str((((choices[0] if choices else {}).get("message") or {}).get("content")) or "").strip()
            usage = payload.get("usage") or {}
            model = str(payload.get("model") or agent.model)
            response_id = payload.get("id")
    if not text:
        raise HTTPException(status_code=502, detail="Provider response contained no text output")
    total_tokens = _usage_total(usage)
    cost_per_1k = float((provider.config or {}).get("cost_per_1k_tokens", 0.0) or 0.0)
    cost = round(total_tokens * cost_per_1k / 1000.0, 8) if cost_per_1k else 0.0
    return {"text": text, "provider": provider.type, "model": model, "usage": {**usage, "total_tokens": total_tokens}, "cost": cost, "latency_ms": round(latency, 2), "response_id": response_id}


async def run_job(job_id: str) -> None:
    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != "queued":
            return
        agent = await session.get(AIAgent, job.agent_id)
        if agent is None:
            job.status = "failed"
            job.error = "Agent no longer exists"
            job.finished_at = _now()
            await session.commit()
            return
        provider = await session.get(AIProvider, agent.provider_id)
        if provider is None:
            job.status = "failed"
            job.error = "Provider no longer exists"
            job.finished_at = _now()
            await session.commit()
            return
        job.status = "running"
        job.started_at = _now()
        agent.status = "running"
        await session.commit()
        requested_by_id = str((job.payload or {}).get("requested_by_id") or "")
        prompt = str((job.payload or {}).get("prompt") or "")

    failure_status_code: int | None = None
    try:
        result = await _execute_provider(provider, agent, prompt)
        failure: str | None = None
    except Exception as exc:
        result = {}
        failure_status_code = exc.status_code if isinstance(exc, HTTPException) else None
        failure = exc.detail if isinstance(exc, HTTPException) else f"Provider execution failed ({type(exc).__name__})"

    async with SessionLocal() as session:
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            return
        agent = await session.get(AIAgent, job.agent_id)
        provider = await session.get(AIProvider, agent.provider_id) if agent else None
        if failure is None:
            job.status = "completed"
            job.result = result
            job.error = None
            job.finished_at = _now()
            if agent is not None:
                metrics = dict(agent.metrics or {})
                metrics["tasks_completed"] = int(metrics.get("tasks_completed", 0) or 0) + 1
                metrics["tokens_used"] = int(metrics.get("tokens_used", 0) or 0) + int((result.get("usage") or {}).get("total_tokens", 0) or 0)
                metrics["cost"] = round(float(metrics.get("cost", 0.0) or 0.0) + float(result.get("cost", 0.0) or 0.0), 8)
                metrics["latency_ms"] = int(float(result.get("latency_ms", 0) or 0))
                agent.metrics = metrics
                agent.status = "idle"
            if provider is not None:
                config = dict(provider.config or {})
                config["usage_today"] = int(config.get("usage_today", 0) or 0) + int((result.get("usage") or {}).get("total_tokens", 0) or 0)
                config["latency_ms"] = int(float(result.get("latency_ms", 0) or 0))
                config["last_used"] = _now().isoformat()
                config["runtime_spend_microusd"] = int(
                    config.get("runtime_spend_microusd", 0) or 0
                ) + usd_to_microusd(float(result.get("cost", 0.0) or 0.0))
                provider.config = config
                provider.status = "connected"
            action = "ai.job.completed"
        else:
            job.status = "failed"
            job.error = str(failure)[:1000]
            job.finished_at = _now()
            if agent is not None:
                metrics = dict(agent.metrics or {})
                metrics["tasks_failed"] = int(metrics.get("tasks_failed", 0) or 0) + 1
                agent.metrics = metrics
                agent.status = "error"
            if provider is not None:
                provider.status = "error"
            action = "ai.job.failed"
        session.add(AuditEvent(organization_id=job.organization_id, user_id=requested_by_id or None, action=action, resource_type="ai_job", resource_id=job.id, details={"agent_id": job.agent_id, "provider_id": provider.id if provider else None, "error": bool(failure)}))
        recipient = await session.get(User, requested_by_id) if requested_by_id else None
        notification = None
        if recipient is not None:
            notification = await communications.create_notification(
                session,
                recipient,
                event_key="ai.job.completed" if failure is None else "ai.job.failed",
                category="project",
                title="AI agent execution completed" if failure is None else "AI agent execution failed",
                message=(f"Agent {agent.name if agent else job.agent_id} completed job {job.id}." if failure is None else f"Agent {agent.name if agent else job.agent_id} failed job {job.id}."),
                severity="success" if failure is None else "warning",
                source_type="ai_job",
                source_id=job.id,
                correlation_id=job.id,
                dedupe_key=f"ai-job:{job.id}:{job.status}",
                actor_id=requested_by_id,
            )
        owner_finance_notifications = []
        if failure is not None and provider is not None:
            normalized_failure = str(failure).lower()
            billing_failure = bool(
                failure_status_code == 402
                or any(marker in normalized_failure for marker in (
                    "insufficient_quota", "billing", "credit", "payment"
                ))
            )
            quota_failure = failure_status_code == 429
            if billing_failure or quota_failure:
                owner_finance_notifications = await notify_provider_billing_failure(
                    session,
                    provider_id=provider.id,
                    failure_code=(
                        "billing_required" if billing_failure else "provider_quota"
                    ),
                    critical=billing_failure,
                )
        await session.commit()
        if notification is not None:
            await communications.publish_realtime(notification)
        await communications.publish_many(owner_finance_notifications)


async def list_agent_jobs(session: AsyncSession, agent_id: str, organization_id: str, limit: int = 20) -> list[dict[str, Any]]:
    await get_agent(session, agent_id, organization_id)
    rows = list((await session.scalars(select(Job).where(Job.organization_id == organization_id, Job.agent_id == agent_id).order_by(Job.created_at.desc()).limit(limit))).all())
    return [job_snapshot(row) for row in rows]
