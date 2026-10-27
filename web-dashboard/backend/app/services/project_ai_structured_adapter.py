"""Project AI-only JSON response adapter; legacy agent provider runtime is unchanged.

This module isolates the large, carefully bounded application-spec request from
general conversation calls. Non-supported provider protocols retain the existing
provider adapter and cannot obtain final approval without strict compiler checks.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.db.models import AIAgent, AIProvider
from app.services.ai_runtime_service import (
    _execute_provider,
    _openai_text,
    _request_json,
    _usage_total,
    provider_credential,
    validate_provider_base_url,
)


async def execute_structured_project_coder(
    provider: AIProvider,
    agent: AIAgent,
    prompt: str,
    *,
    project_coder_max_tokens: int | None = None,
    project_coder_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Request a validated JSON object with an explicit model/output budget.

    The caller must have already authenticated project/tenant scope, checked
    provider evidence, reserved the durable budget and checked external consent.
    This adapter is only for the coder role, never broad agent tool execution.
    """
    tokens = project_coder_max_tokens
    schema = project_coder_schema
    if (
        type(tokens) is not int
        or not 1024 <= tokens <= 4096
        or not isinstance(schema, dict)
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(schema.get("properties"), dict)
        or not isinstance(schema.get("required"), list)
    ):
        raise HTTPException(status_code=422, detail="Project AI product schema or token budget is invalid")
    if provider.type not in {"ollama", "openai"}:
        # Other previously validated providers remain callable via their
        # official adapter, but output validation always happens in the compiler.
        return await _execute_provider(provider, agent, prompt)

    base = validate_provider_base_url(provider.type, provider.base_url)
    if not base:
        raise HTTPException(status_code=503, detail="Project AI provider endpoint is not configured")
    usage: dict[str, Any]
    response_id: str | None
    if provider.type == "ollama":
        request = {
            "model": agent.model,
            "stream": False,
            "messages": (
                ([{"role": "system", "content": agent.system_prompt}]
                 if agent.system_prompt else [])
                + [{"role": "user", "content": prompt}]
            ),
            "format": schema,
            "options": {
                "temperature": 0.0,
                "num_predict": tokens,
            },
        }
        payload, latency = await _request_json(
            "POST",
            f"{base}/api/chat",
            headers={"Content-Type": "application/json"},
            json_body=request,
            timeout=120,
        )
        text = str((payload.get("message") or {}).get("content") or "").strip()
        usage = {
            "input_tokens": int(payload.get("prompt_eval_count") or 0),
            "output_tokens": int(payload.get("eval_count") or 0),
        }
        model_name = str(payload.get("model") or agent.model)
        response_id = None
    else:
        credential = provider_credential(provider)
        if not credential:
            raise HTTPException(status_code=503, detail="Provider credential is not configured")
        request = {
            "model": agent.model,
            "input": prompt,
            "max_output_tokens": tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "aionex_reviewed_product_spec",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        if agent.system_prompt:
            request["instructions"] = agent.system_prompt
        payload, latency = await _request_json(
            "POST",
            f"{base}/v1/responses",
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json_body=request,
            timeout=60,
        )
        text = _openai_text(payload)
        usage = dict(payload.get("usage") or {})
        model_name = str(payload.get("model") or agent.model)
        response_id = payload.get("id")

    if not text or len(text) > 64000:
        raise HTTPException(status_code=502, detail="Project AI structured response was empty or oversized")
    usage["total_tokens"] = _usage_total(usage)
    return {
        "text": text,
        "provider": provider.type,
        "model": model_name,
        "usage": usage,
        "cost": 0.0,  # Authoritative actual pricing is recorded by ProjectAILiveProviderInvoker.
        "latency_ms": round(float(latency), 2),
        "response_id": response_id,
    }
