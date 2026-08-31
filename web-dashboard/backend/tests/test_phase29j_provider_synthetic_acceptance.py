"""Network-free acceptance matrix for every Phase 29J provider contract.

These tests deliberately never contact a third party.  They prove that every agent-runtime
provider reaches the intended request/response adapter, while product-specific 3D providers
remain fail-closed behind their dedicated pipeline.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.services import ai_runtime_service


AGENT_PROVIDER_CASES = {
    "openai": ("https://api.openai.com", "gpt-synthetic"),
    "anthropic": ("https://api.anthropic.com", "claude-synthetic"),
    "gemini": ("https://generativelanguage.googleapis.com", "gemini-synthetic"),
    "openrouter": ("https://openrouter.ai", "router/synthetic"),
    "ollama": ("http://127.0.0.1:11434", "local-synthetic"),
    "mistral": ("https://api.mistral.ai", "mistral-synthetic"),
    "cohere": ("https://api.cohere.com", "command-synthetic"),
    "xai": ("https://api.x.ai", "grok-synthetic"),
    "deepseek": ("https://api.deepseek.com", "deepseek-v4-flash"),
    "groq": ("https://api.groq.com/openai", "groq-synthetic"),
    "together": ("https://api.together.ai", "together/synthetic"),
    "fireworks": ("https://api.fireworks.ai/inference", "accounts/fireworks/models/synthetic"),
    "huggingface": ("https://router.huggingface.co", "org/synthetic:fastest"),
    "azure_openai": ("https://synthetic-resource.openai.azure.com", "azure-synthetic"),
    "aws_bedrock": (None, "bedrock-synthetic"),
}


def _provider(provider_type: str, base_url: str | None) -> Any:
    return SimpleNamespace(
        id=f"provider-{provider_type}",
        organization_id="org-synthetic",
        name=provider_type,
        type=provider_type,
        status="configured",
        encrypted_api_key=None,
        base_url=base_url,
        config={
            "enabled": True,
            "max_output_tokens": 128,
            "cost_per_1k_tokens": 0.01,
            "credential_source": "environment" if provider_type == "aws_bedrock" else "database",
        },
        created_at=None,
    )


def _agent(model: str) -> Any:
    return SimpleNamespace(
        model=model,
        system_prompt="Synthetic acceptance only",
        temperature=0.2,
    )


def _payload_for(provider_type: str, model: str) -> dict[str, Any]:
    if provider_type == "openai":
        return {
            "id": "resp-synthetic-openai",
            "model": model,
            "output_text": "synthetic-ok",
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        }
    if provider_type == "anthropic":
        return {
            "id": "msg-synthetic-anthropic",
            "model": model,
            "content": [{"type": "text", "text": "synthetic-ok"}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }
    if provider_type == "gemini":
        return {
            "responseId": "gemini-synthetic-response",
            "candidates": [{"content": {"parts": [{"text": "synthetic-ok"}]}}],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 2,
                "totalTokenCount": 5,
            },
        }
    if provider_type == "cohere":
        return {
            "id": "cohere-synthetic-response",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "synthetic-ok"}]},
            "usage": {"tokens": {"input_tokens": 3, "output_tokens": 2}},
        }
    if provider_type == "ollama":
        return {
            "model": model,
            "message": {"role": "assistant", "content": "synthetic-ok"},
            "prompt_eval_count": 3,
            "eval_count": 2,
        }
    return {
        "id": f"resp-synthetic-{provider_type}",
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": "synthetic-ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", sorted(AGENT_PROVIDER_CASES))
async def test_every_agent_provider_executes_through_network_free_adapter(
    provider_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url, model = AGENT_PROVIDER_CASES[provider_type]
    provider = _provider(provider_type, base_url)
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        ai_runtime_service,
        "provider_credential",
        lambda item: None if item.type == "ollama" else "synthetic-secret-never-returned",
    )
    monkeypatch.setattr(ai_runtime_service, "_aws_bedrock_configured", lambda: True)
    monkeypatch.setattr(
        ai_runtime_service,
        "_execute_bedrock_sync",
        lambda _agent, _prompt, _max: {
            "text": "synthetic-ok",
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            "model": model,
            "response_id": "bedrock-synthetic-response",
            "latency_ms": 12.5,
        },
    )

    async def fake_request_json(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> tuple[dict[str, Any], float]:
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": json_body,
                "timeout": timeout,
            }
        )
        return _payload_for(provider_type, model), 12.5

    monkeypatch.setattr(ai_runtime_service, "_request_json", fake_request_json)
    result = await ai_runtime_service._execute_provider(
        provider,
        _agent(model),
        "synthetic provider acceptance",
    )

    assert result["provider"] == provider_type
    assert result["model"] == model
    assert result["text"] == "synthetic-ok"
    assert result["usage"]["total_tokens"] == 5
    assert result["latency_ms"] == 12.5
    assert "synthetic-secret-never-returned" not in repr(result)
    if provider_type == "aws_bedrock":
        assert calls == []
        return
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["body"] is not None
    if provider_type != "gemini":
        assert calls[0]["body"]["model"] == model

    expected_urls = {
        "openai": "https://api.openai.com/v1/responses",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        "ollama": "http://127.0.0.1:11434/api/chat",
        "mistral": "https://api.mistral.ai/v1/chat/completions",
        "cohere": "https://api.cohere.com/v2/chat",
        "xai": "https://api.x.ai/v1/chat/completions",
        "deepseek": "https://api.deepseek.com/v1/chat/completions",
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "together": "https://api.together.ai/v1/chat/completions",
        "fireworks": "https://api.fireworks.ai/inference/v1/chat/completions",
        "huggingface": "https://router.huggingface.co/v1/chat/completions",
        "azure_openai": "https://synthetic-resource.openai.azure.com/openai/v1/chat/completions",
    }
    if provider_type == "gemini":
        assert calls[0]["url"].endswith("/v1beta/models/gemini-synthetic:generateContent")
        assert "systemInstruction" in calls[0]["body"]
    else:
        assert calls[0]["url"] == expected_urls[provider_type]
    if provider_type == "openai":
        assert calls[0]["body"]["store"] is False
    if provider_type == "anthropic":
        assert calls[0]["headers"]["anthropic-version"] == "2023-06-01"
    if provider_type == "ollama":
        assert calls[0]["body"]["stream"] is False
    if provider_type == "azure_openai":
        assert "api-key" in calls[0]["headers"]


def test_synthetic_matrix_covers_every_general_agent_provider() -> None:
    assert set(AGENT_PROVIDER_CASES) == set(ai_runtime_service.AGENT_RUNTIME_PROVIDER_TYPES)
    assert ai_runtime_service.DEDICATED_3D_PROVIDER_TYPES == {"tripo3d", "meshy"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", ["tripo3d", "meshy"])
async def test_3d_providers_never_fall_through_generic_chat_execution(
    provider_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden_request(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], float]:
        raise AssertionError("dedicated 3D providers must not reach the general chat transport")

    monkeypatch.setattr(ai_runtime_service, "_request_json", forbidden_request)
    with pytest.raises(HTTPException) as exc:
        await ai_runtime_service._execute_provider(
            _provider(provider_type, f"https://{provider_type}.invalid"),
            _agent("3d-synthetic"),
            "synthetic",
        )
    assert exc.value.status_code == 422
    assert "not executable through the AI agent runtime" in str(exc.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", ["tripo3d", "meshy"])
async def test_3d_health_is_truthfully_delegated(provider_type: str) -> None:
    result = await ai_runtime_service.provider_health_probe(
        _provider(provider_type, f"https://{provider_type}.invalid")
    )
    assert result == {
        "status": "catalog_only",
        "latency_ms": 0,
        "message": "Tripo3D/Meshy are catalog connectors only; production 3D health is owned by the Hunyuan3D/TripoSR RunPod pipeline",
    }


@pytest.mark.asyncio
async def test_empty_synthetic_provider_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider("openai", "https://api.openai.com")
    monkeypatch.setattr(ai_runtime_service, "provider_credential", lambda _item: "synthetic")

    async def empty_request(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], float]:
        return {"id": "empty", "output_text": "", "usage": {}}, 1.0

    monkeypatch.setattr(ai_runtime_service, "_request_json", empty_request)
    with pytest.raises(HTTPException) as exc:
        await ai_runtime_service._execute_provider(provider, _agent("gpt-synthetic"), "x")
    assert exc.value.status_code == 502
    assert exc.value.detail == "Provider response contained no text output"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", sorted(AGENT_PROVIDER_CASES))
async def test_every_agent_provider_health_contract_is_synthetically_exercised(
    provider_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url, _model = AGENT_PROVIDER_CASES[provider_type]
    provider = _provider(provider_type, base_url)
    calls: list[str] = []
    allow_array_calls: list[bool] = []

    monkeypatch.setattr(
        ai_runtime_service,
        "provider_credential",
        lambda item: None if item.type == "ollama" else "synthetic-health-secret",
    )
    monkeypatch.setattr(ai_runtime_service, "_aws_bedrock_configured", lambda: True)

    async def fake_request_json(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0,
        allow_array: bool = False,
    ) -> tuple[dict[str, Any], float]:
        del method, headers, json_body, timeout
        calls.append(url)
        allow_array_calls.append(allow_array)
        return {"data": []}, 7.25

    monkeypatch.setattr(ai_runtime_service, "_request_json", fake_request_json)

    class FakeStsClient:
        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": "000000000000"}

    monkeypatch.setattr(ai_runtime_service.boto3, "client", lambda *_args, **_kwargs: FakeStsClient())
    result = await ai_runtime_service.provider_health_probe(provider)

    if provider_type in {"anthropic", "cohere"}:
        assert result["status"] == "configured"
        assert result["latency_ms"] == 0
        assert calls == []
        assert allow_array_calls == []
    elif provider_type == "aws_bedrock":
        assert result["status"] == "success"
        assert result["latency_ms"] >= 0
        assert "AWS credential identity verified" in result["message"]
        assert calls == []
        assert allow_array_calls == []
    else:
        assert result == {
            "status": "success",
            "latency_ms": 7.25,
            "message": "Provider endpoint verified",
        }
        assert len(calls) == 1
        assert allow_array_calls == ([True] if provider_type == "together" else [False])


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", ["tripo3d", "meshy"])
async def test_general_provider_creation_rejects_dedicated_3d_providers(
    provider_type: str,
) -> None:
    with pytest.raises(HTTPException) as exc:
        await ai_runtime_service.create_provider(
            None,  # type: ignore[arg-type]
            {
                "type": provider_type,
                "name": f"Synthetic {provider_type}",
                "api_key": "synthetic-never-stored",
                "base_url": f"https://{provider_type}.invalid",
            },
            "org-synthetic",
            "owner-synthetic",
        )
    assert exc.value.status_code == 422
    assert "not executable through the AI agent runtime" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_aws_health_rejects_invalid_identity_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider("aws_bedrock", None)
    monkeypatch.setattr(ai_runtime_service, "_aws_bedrock_configured", lambda: True)

    class InvalidStsClient:
        def get_caller_identity(self) -> dict[str, str]:
            raise ai_runtime_service.ClientError(
                {"Error": {"Code": "InvalidClientTokenId", "Message": "invalid"}},
                "GetCallerIdentity",
            )

    monkeypatch.setattr(ai_runtime_service.boto3, "client", lambda *_args, **_kwargs: InvalidStsClient())
    with pytest.raises(HTTPException) as exc:
        await ai_runtime_service.provider_health_probe(provider)
    assert exc.value.status_code == 502
    assert "AWS credential identity validation failed" in str(exc.value.detail)
