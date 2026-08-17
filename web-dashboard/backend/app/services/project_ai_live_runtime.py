"""Production Phase 36C runner factory and provider invocation adapter.

The factory remains dormant while ``PROJECT_EXECUTION_RUNNER_MODE=legacy``.  When
explicitly selected later, it resolves Owner-governed Free/Paid/user policy for
each ProjectExecution, reuses the existing provider runtime transports, verifies
fresh validated-model evidence, and emits only redacted provider failure codes.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import AIAgent, AIProvider, ProjectExecution
from app.services import communications
from app.services.ai_runtime_service import _execute_provider, provider_enabled
from app.services.project_ai_access_policy import (
    ProjectAIAccessPolicyError,
    resolve_project_ai_access,
)
from app.services.project_execution_ai_integration import (
    DeterministicProjectAIIntegrationRunner,
    ProjectAIIntegrationError,
    ProjectAIInvocation,
    ProjectAIInvocationFailure,
    ProjectAIInvocationResult,
    default_project_ai_tasks,
)
from app.services.project_execution_routing import (
    ProjectAIProviderPolicy,
    ProjectAIScope,
    ProjectAITaskSpec,
)
from app.services.provider_credit_alerts import notify_provider_billing_failure


class ProjectAILiveRuntimeError(RuntimeError):
    """The live provider invocation cannot proceed safely."""


def _utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _validated_entry(provider: AIProvider, invocation: ProjectAIInvocation) -> dict[str, Any]:
    config = dict(provider.config or {})
    rows = config.get("validated_models")
    if not isinstance(rows, list):
        raise ProjectAIInvocationFailure("provider_model_evidence_missing")
    current = datetime.now(UTC)
    matches: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("model") or "") != invocation.model:
            continue
        if str(raw.get("evidence_ref") or "") != invocation.evidence_ref:
            continue
        expires = _utc(raw.get("expires_at"))
        validated = _utc(raw.get("validated_at"))
        if validated is None or expires is None or validated > current or expires <= current:
            continue
        matches.append(raw)
    if len(matches) != 1:
        raise ProjectAIInvocationFailure("provider_model_evidence_invalid")
    return matches[0]


def _usage_tokens(usage: dict[str, Any]) -> tuple[int, int]:
    input_tokens = int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("promptTokenCount")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("candidatesTokenCount")
        or 0
    )
    total = int(usage.get("total_tokens") or usage.get("totalTokenCount") or 0)
    if input_tokens < 0 or output_tokens < 0 or total < 0:
        raise ProjectAIInvocationFailure("provider_usage_invalid")
    if input_tokens == 0 and output_tokens == 0 and total > 0:
        # Fail conservative for billing if the provider only returns a total.
        output_tokens = total
    return input_tokens, output_tokens


def _cost_usd(entry: dict[str, Any], input_tokens: int, output_tokens: int) -> float:
    input_price = float(entry.get("input_cost_per_million", -1))
    output_price = float(entry.get("output_cost_per_million", -1))
    if input_price < 0 or output_price < 0:
        raise ProjectAIInvocationFailure("provider_price_evidence_invalid")
    return round(
        (input_tokens * input_price + output_tokens * output_price) / 1_000_000.0,
        8,
    )


def _provider_error_code(exc: HTTPException) -> tuple[str, bool | None]:
    detail = str(exc.detail or "").lower()
    if "http 402" in detail or "payment" in detail or "billing" in detail:
        return "provider_billing", True
    if "http 429" in detail or "quota" in detail or "rate limit" in detail:
        return "provider_quota", False
    if "http 401" in detail or "http 403" in detail or "credential" in detail:
        return "provider_auth", None
    if exc.status_code == 503:
        return "provider_unavailable", None
    if "invalid json" in detail or "no text" in detail or "response" in detail:
        return "provider_response", None
    return "provider_transport", None


class ProjectAILiveProviderInvoker:
    """Generic validated-model invoker backed by the Phase29J runtime adapters."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    ) -> None:
        self.session_factory = session_factory

    async def __call__(self, invocation: ProjectAIInvocation) -> ProjectAIInvocationResult:
        async with self.session_factory() as session:
            provider = await session.get(AIProvider, invocation.provider_id)
            if provider is None:
                raise ProjectAIInvocationFailure("provider_not_found")
            if provider.type.strip().lower() != invocation.provider.strip().lower():
                raise ProjectAIInvocationFailure("provider_scope_mismatch")
            if provider.status != "connected" or not provider_enabled(provider):
                raise ProjectAIInvocationFailure("provider_unavailable")
            entry = _validated_entry(provider, invocation)

        agent = AIAgent(
            organization_id=invocation.scope.organization_id,
            workspace_id=invocation.scope.workspace_id,
            provider_id=invocation.provider_id,
            name="Project AI Live Runtime",
            slug=f"project-ai-{invocation.role}",
            role=invocation.role,
            department="Project AI",
            model=invocation.model,
            status="running",
            system_prompt=invocation.system_prompt or None,
            temperature=0.2,
            metrics={},
        )
        try:
            result = await _execute_provider(provider, agent, invocation.prompt)
        except HTTPException as exc:
            code, billing_signal = _provider_error_code(exc)
            if billing_signal is not None:
                async with self.session_factory() as session:
                    notifications = await notify_provider_billing_failure(
                        session,
                        provider_id=invocation.provider_id,
                        failure_code=code,
                        critical=billing_signal,
                    )
                    await session.commit()
                await communications.publish_many(notifications)
            raise ProjectAIInvocationFailure(code) from exc
        except Exception as exc:
            raise ProjectAIInvocationFailure("provider_transport") from exc

        usage = dict(result.get("usage") or {})
        input_tokens, output_tokens = _usage_tokens(usage)
        cost = _cost_usd(entry, input_tokens, output_tokens)
        text = str(result.get("text") or "").strip()
        if not text:
            raise ProjectAIInvocationFailure("provider_response")
        latency = float(result.get("latency_ms", 0.0) or 0.0)
        if latency < 0:
            raise ProjectAIInvocationFailure("provider_usage_invalid")
        return ProjectAIInvocationResult(
            text=text,
            cost_usd=cost,
            latency_ms=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            memory_note=f"{invocation.provider}:{invocation.model}:{invocation.role}:completed",
        )


async def resolve_live_project_ai_policy(scope: ProjectAIScope) -> ProjectAIProviderPolicy:
    async with SessionLocal() as session:
        execution = await session.get(ProjectExecution, scope.execution_id)
        if execution is None:
            raise ProjectAIIntegrationError("ProjectExecution was not found for live policy")
        try:
            access = await resolve_project_ai_access(
                session,
                organization_id=scope.organization_id,
                user_id=execution.requested_by_id,
            )
        except ProjectAIAccessPolicyError as exc:
            raise ProjectAIIntegrationError("Project AI Owner access policy blocked execution") from exc
        return access.policy


def launch_policy_tasks(
    project_name: str,
    objective: str,
    policy: ProjectAIProviderPolicy,
) -> tuple[ProjectAITaskSpec, ...]:
    tasks = default_project_ai_tasks(project_name, objective)
    return tuple(
        replace(
            task,
            require_tools=(task.require_tools and not policy.offline_only),
            allow_failover=policy.max_fallbacks > 0,
            max_fallbacks=policy.max_fallbacks,
        )
        for task in tasks
    )


def build_live_project_ai_runner() -> DeterministicProjectAIIntegrationRunner:
    """Build the production-capable runner; caller still controls the mode switch."""

    return DeterministicProjectAIIntegrationRunner(
        session_factory=SessionLocal,
        redis_url=settings.REDIS_URL,
        policy_resolver=resolve_live_project_ai_policy,
        default_invoker=ProjectAILiveProviderInvoker(SessionLocal),
        policy_task_factory=launch_policy_tasks,
        redis_key_prefix="aionex:project-ai:live:v1",
    )
