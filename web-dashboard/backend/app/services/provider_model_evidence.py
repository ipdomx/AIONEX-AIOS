"""Phase 36C provider-specific model evidence authority.

This module separates live inventory/execution evidence from the historical static
provider capability catalogue.  It never reads provider credentials into durable
records and never treats ``model=default`` or static catalogue scores as live proof.
Network calls occur only when ``probe_provider_model_inventory`` is explicitly
invoked; tests inject a deterministic requester.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIProvider, AuditEvent
from app.services.ai_runtime_service import (
    _chat_api_root,
    _request_json,
    provider_credential,
    provider_enabled,
    validate_provider_base_url,
)


class ProviderModelEvidenceError(RuntimeError):
    """Provider model evidence cannot be proven safely."""


INVENTORY_PROVIDER_TYPES = frozenset(
    {
        "openai",
        "gemini",
        "openrouter",
        "ollama",
        "mistral",
        "xai",
        "deepseek",
        "groq",
        "together",
        "fireworks",
        "huggingface",
        "azure_openai",
    }
)
EXECUTION_EVIDENCE_PROVIDER_TYPES = frozenset({"anthropic", "cohere", "aws_bedrock"})

Requester = Callable[..., Awaitable[tuple[Any, float]]]


def _now() -> datetime:
    return datetime.now(UTC)


def _required(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProviderModelEvidenceError(f"{label} is required")
    return text


def _model_id(value: Any) -> str:
    model = _required(value, "model id")
    if model.startswith("models/"):
        model = model.removeprefix("models/")
    if not model or model.lower() == "default" or len(model) > 300:
        raise ProviderModelEvidenceError("model id is not valid live evidence")
    return model


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None:
        raise ProviderModelEvidenceError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ProviderModelInventoryEvidence:
    provider_id: str
    provider_type: str
    model_ids: tuple[str, ...]
    evidence_ref: str
    observed_at: datetime
    latency_ms: float

    def __post_init__(self) -> None:
        provider_id = _required(self.provider_id, "provider_id")
        provider_type = _required(self.provider_type, "provider_type").lower()
        if provider_type not in INVENTORY_PROVIDER_TYPES:
            raise ProviderModelEvidenceError(
                f"provider {provider_type} does not have an accepted model inventory proof"
            )
        models = tuple(sorted({_model_id(item) for item in self.model_ids}))
        if not models:
            raise ProviderModelEvidenceError("provider model inventory is empty")
        if len(models) > 10000:
            raise ProviderModelEvidenceError("provider model inventory is unreasonably large")
        evidence_ref = _required(self.evidence_ref, "evidence_ref")
        observed_at = _utc(self.observed_at, "observed_at")
        if self.latency_ms < 0:
            raise ProviderModelEvidenceError("inventory latency must be non-negative")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "provider_type", provider_type)
        object.__setattr__(self, "model_ids", models)
        object.__setattr__(self, "evidence_ref", evidence_ref)
        object.__setattr__(self, "observed_at", observed_at)


@dataclass(frozen=True, slots=True)
class ProviderModelExecutionEvidence:
    provider_id: str
    provider_type: str
    model: str
    passed_tasks: frozenset[str]
    evidence_ref: str
    observed_at: datetime

    def __post_init__(self) -> None:
        provider_type = _required(self.provider_type, "provider_type").lower()
        if provider_type not in EXECUTION_EVIDENCE_PROVIDER_TYPES:
            raise ProviderModelEvidenceError(
                f"provider {provider_type} must use inventory evidence instead"
            )
        tasks = frozenset(_required(item, "passed task").lower() for item in self.passed_tasks)
        if not tasks:
            raise ProviderModelEvidenceError("execution evidence requires passed tasks")
        object.__setattr__(self, "provider_id", _required(self.provider_id, "provider_id"))
        object.__setattr__(self, "provider_type", provider_type)
        object.__setattr__(self, "model", _model_id(self.model))
        object.__setattr__(self, "passed_tasks", tasks)
        object.__setattr__(self, "evidence_ref", _required(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))


@dataclass(frozen=True, slots=True)
class ProviderModelValidationSpec:
    provider_type: str
    model: str
    tasks: frozenset[str]
    policy_ref: str
    languages: frozenset[str] = frozenset({"multilingual"})
    supports_tools: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    local: bool = False
    max_context_tokens: int = 8192
    quality_score: float = 0.5
    latency_score: float = 0.5
    privacy_score: float = 0.5
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    requests_per_minute: int = 60
    concurrent_requests: int = 1
    circuit_failure_threshold: int = 3
    circuit_failure_window_seconds: int = 60
    circuit_open_seconds: int = 60
    lease_seconds: int = 120

    def __post_init__(self) -> None:
        provider_type = _required(self.provider_type, "provider_type").lower()
        model = _model_id(self.model)
        tasks = frozenset(_required(item, "task").lower() for item in self.tasks)
        if not tasks:
            raise ProviderModelEvidenceError("validation policy requires explicit tasks")
        languages = frozenset(_required(item, "language") for item in self.languages)
        if not languages:
            raise ProviderModelEvidenceError("validation policy requires explicit languages")
        if self.max_context_tokens <= 0:
            raise ProviderModelEvidenceError("max_context_tokens must be positive")
        for label, value in (
            ("quality_score", self.quality_score),
            ("latency_score", self.latency_score),
            ("privacy_score", self.privacy_score),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ProviderModelEvidenceError(f"{label} must be between 0 and 1")
        if self.input_cost_per_million < 0 or self.output_cost_per_million < 0:
            raise ProviderModelEvidenceError("model prices must be non-negative")
        for label, value, minimum, maximum in (
            ("requests_per_minute", self.requests_per_minute, 1, 100000),
            ("concurrent_requests", self.concurrent_requests, 1, 10000),
            ("circuit_failure_threshold", self.circuit_failure_threshold, 1, 1000),
            ("circuit_failure_window_seconds", self.circuit_failure_window_seconds, 1, 86400),
            ("circuit_open_seconds", self.circuit_open_seconds, 1, 86400),
            ("lease_seconds", self.lease_seconds, 5, 3600),
        ):
            if not minimum <= int(value) <= maximum:
                raise ProviderModelEvidenceError(
                    f"{label} must be between {minimum} and {maximum}"
                )
        object.__setattr__(self, "provider_type", provider_type)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "languages", languages)
        object.__setattr__(self, "policy_ref", _required(self.policy_ref, "policy_ref"))

    def validated_entry(
        self,
        *,
        evidence_ref: str,
        validated_at: datetime,
        ttl: timedelta,
    ) -> dict[str, Any]:
        if ttl <= timedelta(0) or ttl > timedelta(days=30):
            raise ProviderModelEvidenceError("validated model TTL must be between 1 second and 30 days")
        validated_at = _utc(validated_at, "validated_at")
        expires_at = validated_at + ttl
        return {
            "model": self.model,
            "tasks": sorted(self.tasks),
            "evidence_ref": evidence_ref,
            "policy_ref": self.policy_ref,
            "validated_at": validated_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "languages": sorted(self.languages),
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "supports_audio": self.supports_audio,
            "local": self.local,
            "max_context_tokens": self.max_context_tokens,
            "quality_score": float(self.quality_score),
            "latency_score": float(self.latency_score),
            "privacy_score": float(self.privacy_score),
            "input_cost_per_million": float(self.input_cost_per_million),
            "output_cost_per_million": float(self.output_cost_per_million),
            "requests_per_minute": int(self.requests_per_minute),
            "concurrent_requests": int(self.concurrent_requests),
            "circuit_failure_threshold": int(self.circuit_failure_threshold),
            "circuit_failure_window_seconds": int(self.circuit_failure_window_seconds),
            "circuit_open_seconds": int(self.circuit_open_seconds),
            "lease_seconds": int(self.lease_seconds),
        }


def parse_provider_model_inventory(provider_type: str, payload: Any) -> tuple[str, ...]:
    provider_type = _required(provider_type, "provider_type").lower()
    if provider_type not in INVENTORY_PROVIDER_TYPES:
        raise ProviderModelEvidenceError(
            f"provider {provider_type} requires execution evidence instead of model inventory"
        )
    rows: Any
    if provider_type == "together":
        rows = payload
    elif not isinstance(payload, dict):
        raise ProviderModelEvidenceError("model inventory payload must be an object")
    elif provider_type in {"gemini", "ollama"}:
        rows = payload.get("models")
    else:
        rows = payload.get("data")
    if not isinstance(rows, list):
        raise ProviderModelEvidenceError("model inventory payload has no accepted model list")
    models: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("id")
        if raw is None:
            raw = row.get("name")
        if raw is None and provider_type == "ollama":
            raw = row.get("model")
        if raw is None:
            continue
        models.append(_model_id(raw))
    result = tuple(sorted(set(models)))
    if not result:
        raise ProviderModelEvidenceError("provider model inventory contained no model ids")
    return result


async def probe_provider_model_inventory(
    provider: AIProvider,
    *,
    requester: Requester = _request_json,
    observed_at: datetime | None = None,
) -> ProviderModelInventoryEvidence:
    provider_type = provider.type.strip().lower()
    if provider_type in EXECUTION_EVIDENCE_PROVIDER_TYPES:
        raise ProviderModelEvidenceError(
            f"provider {provider_type} requires bounded execution evidence"
        )
    if provider_type not in INVENTORY_PROVIDER_TYPES:
        raise ProviderModelEvidenceError(f"provider {provider_type} is not a Phase36C AI inventory provider")
    if provider.status != "connected" or not provider_enabled(provider):
        raise ProviderModelEvidenceError("provider must be connected and enabled")
    base = validate_provider_base_url(provider_type, provider.base_url)
    if not base:
        raise ProviderModelEvidenceError("provider endpoint is not configured")
    credential = provider_credential(provider)
    if provider_type != "ollama" and not credential:
        raise ProviderModelEvidenceError("provider credential is not configured")
    headers: dict[str, str] = {"Accept": "application/json"}
    allow_array = False
    if provider_type == "openai":
        url = f"{base}/v1/models"
        headers["Authorization"] = f"Bearer {credential}"
    elif provider_type == "gemini":
        url = f"{base}/v1beta/models"
        headers["x-goog-api-key"] = str(credential)
    elif provider_type == "ollama":
        url = f"{base}/api/tags"
    elif provider_type == "azure_openai":
        url = f"{_chat_api_root(provider_type, base)}/models"
        headers["api-key"] = str(credential)
    elif provider_type == "together":
        url = f"{_chat_api_root(provider_type, base)}/models"
        headers["Authorization"] = f"Bearer {credential}"
        allow_array = True
    else:
        url = f"{_chat_api_root(provider_type, base)}/models"
        headers["Authorization"] = f"Bearer {credential}"
    try:
        payload, latency = await requester(
            "GET", url, headers=headers, timeout=30.0, allow_array=allow_array
        )
    except HTTPException as exc:
        raise ProviderModelEvidenceError(
            f"provider model inventory probe failed ({exc.status_code})"
        ) from exc
    model_ids = parse_provider_model_inventory(provider_type, payload)
    current = _utc(observed_at or _now(), "observed_at")
    canonical = json.dumps(model_ids, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(
        f"{provider.id}\0{provider_type}\0{canonical}".encode("utf-8")
    ).hexdigest()
    return ProviderModelInventoryEvidence(
        provider_id=provider.id,
        provider_type=provider_type,
        model_ids=model_ids,
        evidence_ref=f"phase36c:provider-model-inventory:{digest}",
        observed_at=current,
        latency_ms=float(latency),
    )


def build_validated_model_from_inventory(
    evidence: ProviderModelInventoryEvidence,
    spec: ProviderModelValidationSpec,
    *,
    now: datetime | None = None,
    max_evidence_age: timedelta = timedelta(hours=1),
    ttl: timedelta = timedelta(days=1),
) -> dict[str, Any]:
    current = _utc(now or _now(), "now")
    if spec.provider_type != evidence.provider_type:
        raise ProviderModelEvidenceError("provider type does not match inventory evidence")
    if spec.model not in evidence.model_ids:
        raise ProviderModelEvidenceError("model is absent from provider inventory evidence")
    if evidence.observed_at > current + timedelta(minutes=1):
        raise ProviderModelEvidenceError("provider inventory evidence is future-dated")
    if current - evidence.observed_at > max_evidence_age:
        raise ProviderModelEvidenceError("provider inventory evidence is stale")
    ref = f"{evidence.evidence_ref}:{hashlib.sha256(spec.policy_ref.encode('utf-8')).hexdigest()[:16]}"
    return spec.validated_entry(evidence_ref=ref, validated_at=current, ttl=ttl)


def build_validated_model_from_execution(
    evidence: ProviderModelExecutionEvidence,
    spec: ProviderModelValidationSpec,
    *,
    now: datetime | None = None,
    max_evidence_age: timedelta = timedelta(hours=1),
    ttl: timedelta = timedelta(days=1),
) -> dict[str, Any]:
    current = _utc(now or _now(), "now")
    if spec.provider_type != evidence.provider_type or spec.model != evidence.model:
        raise ProviderModelEvidenceError("execution evidence does not match provider/model policy")
    if not spec.tasks.issubset(evidence.passed_tasks):
        raise ProviderModelEvidenceError("execution evidence did not pass every required task")
    if evidence.observed_at > current + timedelta(minutes=1):
        raise ProviderModelEvidenceError("provider execution evidence is future-dated")
    if current - evidence.observed_at > max_evidence_age:
        raise ProviderModelEvidenceError("provider execution evidence is stale")
    ref = f"{evidence.evidence_ref}:{hashlib.sha256(spec.policy_ref.encode('utf-8')).hexdigest()[:16]}"
    return spec.validated_entry(evidence_ref=ref, validated_at=current, ttl=ttl)


async def persist_provider_validated_model(
    session: AsyncSession,
    *,
    organization_id: str,
    provider_id: str,
    actor_id: str | None,
    entry: dict[str, Any],
) -> AIProvider:
    provider = await session.scalar(
        select(AIProvider)
        .where(
            AIProvider.id == provider_id,
            AIProvider.organization_id == organization_id,
        )
        .with_for_update()
    )
    if provider is None:
        raise ProviderModelEvidenceError("provider was not found in organization scope")
    if provider.status != "connected" or not provider_enabled(provider):
        raise ProviderModelEvidenceError("provider must be connected and enabled")
    model = _model_id(entry.get("model"))
    if provider.type.strip().lower() != _required(entry.get("provider_type", provider.type), "provider_type").lower():
        raise ProviderModelEvidenceError("validated model provider type mismatch")
    evidence_ref = _required(entry.get("evidence_ref"), "evidence_ref")
    _required(entry.get("validated_at"), "validated_at")
    _required(entry.get("expires_at"), "expires_at")
    config = dict(provider.config or {})
    existing = config.get("validated_models")
    rows = [dict(item) for item in existing] if isinstance(existing, list) else []
    rows = [item for item in rows if str(item.get("model") or "") != model]
    stored = dict(entry)
    stored.pop("provider_type", None)
    rows.append(stored)
    rows.sort(key=lambda item: str(item.get("model") or ""))
    if len(rows) > 64:
        raise ProviderModelEvidenceError("provider validated model evidence exceeds safe limit")
    config["validated_models"] = rows
    provider.config = config
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="provider.model_evidence.validated",
            resource_type="ai_provider",
            resource_id=provider.id,
            details={
                "provider": provider.type,
                "model": model,
                "evidence_ref": evidence_ref,
                "policy_ref": entry.get("policy_ref"),
                "expires_at": entry.get("expires_at"),
            },
        )
    )
    await session.flush()
    return provider
