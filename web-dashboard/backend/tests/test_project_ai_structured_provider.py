"""Network-disabled provider request correctness for the executable Project AI compiler."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from aios.controlled_project_builder import ControlledProjectBuilder
from app.services import ai_runtime_service
from app.services import project_ai_structured_adapter as structured


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("provider_type", ["ollama", "openai"])
async def test_reviewed_coder_structured_request_is_bounded_and_no_model_network(
    monkeypatch: pytest.MonkeyPatch, provider_type: str,
) -> None:
    request: dict = {}
    model = "gemma3:4b" if provider_type == "ollama" else "gpt-synthetic"
    url = "http://127.0.0.1:11434" if provider_type == "ollama" else "https://api.openai.com"
    provider = SimpleNamespace(
        type=provider_type,
        config={"max_output_tokens": 1024},
        base_url=url,
        id="test-provider",
    )
    agent = SimpleNamespace(model=model, system_prompt="Product JSON only", temperature=0.7)

    async def fake_json(method, address, **kwargs):
        assert method == "POST"
        assert address.startswith(url)
        assert kwargs["timeout"] <= 120
        request.update(kwargs["json_body"])
        if provider_type == "ollama":
            return {"model": model, "message": {"content": '{"schema_version":3}'}, "prompt_eval_count": 200, "eval_count": 300}, 12.0
        return {"model": model, "output_text": '{"schema_version":3}', "usage": {"input_tokens": 200, "output_tokens": 300}}, 12.0

    monkeypatch.setattr(structured, "_request_json", fake_json)
    monkeypatch.setattr(structured, "provider_credential", lambda _provider: None if provider_type == "ollama" else "synthetic-only")
    result = await structured.execute_structured_project_coder(
        provider, agent, "Create the structured product specification",
        project_coder_max_tokens=3072,
        project_coder_schema=ControlledProjectBuilder._schema(),
    )
    assert result["text"] == '{"schema_version":3}'
    assert result["usage"]["total_tokens"] == 500
    if provider_type == "ollama":
        assert request["options"]["num_predict"] == 3072
        assert request["options"]["num_thread"] == 6
        assert request["options"]["num_ctx"] == 4096
        assert request["options"]["temperature"] == 0.0
        assert request["format"] == ControlledProjectBuilder._schema()
        assert request["stream"] is False
    else:
        assert request["store"] is False
        assert request["max_output_tokens"] == 3072
        assert request["text"]["format"]["strict"] is True
        assert request["text"]["format"]["schema"] == ControlledProjectBuilder._schema()


@pytest.mark.anyio
@pytest.mark.parametrize("tokens", [None, 0, 1023, 4097, True, "3072"])
async def test_invalid_coder_token_override_and_schema_cannot_make_network_call(
    monkeypatch: pytest.MonkeyPatch, tokens,
) -> None:
    called = False

    async def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("no network expected")

    monkeypatch.setattr(structured, "_request_json", forbidden)
    provider = SimpleNamespace(type="ollama", config={}, base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="local", temperature=0, system_prompt="")
    with pytest.raises(HTTPException) as exc:
        await structured.execute_structured_project_coder(
            provider, agent, "json",
            project_coder_max_tokens=tokens,
            project_coder_schema=ControlledProjectBuilder._schema(),
        )
    assert exc.value.status_code == 422
    assert called is False


@pytest.mark.anyio
async def test_regular_agent_request_keeps_legacy_token_budget_and_no_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def stub(_method, _url, **kwargs):
        captured.update(kwargs["json_body"])
        return {"model": "gemma3:4b", "message": {"content": "normal"}, "prompt_eval_count": 5, "eval_count": 4}, 1

    monkeypatch.setattr(ai_runtime_service, "_request_json", stub)
    monkeypatch.setattr(ai_runtime_service, "provider_credential", lambda _: None)
    p = SimpleNamespace(type="ollama", config={}, base_url="http://127.0.0.1:11434")
    a = SimpleNamespace(model="gemma3:4b", temperature=0.4, system_prompt="")
    result = await ai_runtime_service._execute_provider(p, a, "regular chat")
    assert result["text"] == "normal"
    assert captured["options"]["num_predict"] == 1024
    assert "format" not in captured



@pytest.mark.anyio
async def test_free_ollama_non_coder_roles_use_real_bounded_six_cpu_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = {}

    async def local_only_request(method, address, **kwargs):
        assert method == "POST"
        assert address == "http://127.0.0.1:11434/api/chat"
        sent.update(kwargs["json_body"])
        return {
            "model": "gemma3:4b",
            "message": {"content": "Reviewed synthetic planning summary"},
            "prompt_eval_count": 130,
            "eval_count": 35,
        }, 4200

    monkeypatch.delenv("PROJECT_AI_OLLAMA_THREADS", raising=False)
    monkeypatch.setattr(structured, "_request_json", local_only_request)
    provider = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="gemma3:4b", temperature=0.2, system_prompt="No invented tests.")
    result = await structured.execute_local_project_role(
        provider, agent, "Create a bounded research summary", max_output_tokens=192
    )
    assert sent["options"] == {
        "temperature": 0.2, "num_predict": 192, "num_ctx": 4096, "num_thread": 6,
    }
    assert sent["stream"] is False
    assert "format" not in sent
    assert result["usage"] == {"input_tokens": 130, "output_tokens": 35, "total_tokens": 165}
    assert result["text"] == "Reviewed synthetic planning summary"
    assert result["cost"] == 0.0


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", [0, 193, True, "192"])
async def test_local_reasoning_role_invalid_token_budget_prevents_network(
    monkeypatch: pytest.MonkeyPatch, invalid,
) -> None:
    called = False

    async def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("invalid role budget must not call local model")

    monkeypatch.setattr(structured, "_request_json", forbidden)
    provider = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="gemma3:4b", temperature=0.2, system_prompt="")
    with pytest.raises(HTTPException) as exc:
        await structured.execute_local_project_role(provider, agent, "Plan synthetic task", max_output_tokens=invalid)
    assert exc.value.status_code == 422 and not called


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", ["0", "9", "banana", ""])
async def test_local_cpu_thread_config_is_fail_closed_and_never_calls_provider(
    monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    calls = []

    async def blocked(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("invalid thread budget must fail before network")

    monkeypatch.setenv("PROJECT_AI_OLLAMA_THREADS", invalid)
    monkeypatch.setattr(structured, "_request_json", blocked)
    p = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    a = SimpleNamespace(model="gemma3:4b", temperature=0.2, system_prompt="")
    with pytest.raises(HTTPException) as exc:
        await structured.execute_local_project_role(p, a, "No production job")
    assert exc.value.status_code == 503 and not calls


@pytest.mark.anyio
async def test_local_cpu_thread_budget_is_configurable_but_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []

    async def local_request(_method, _url, **kwargs):
        observed.append(kwargs["json_body"]["options"]["num_thread"])
        return {
            "model": "gemma3:4b", "message": {"content": "Reviewed"},
            "prompt_eval_count": 20, "eval_count": 10,
        }, 3
    monkeypatch.setenv("PROJECT_AI_OLLAMA_THREADS", "4")
    monkeypatch.setattr(structured, "_request_json", local_request)
    p = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    a = SimpleNamespace(model="gemma3:4b", temperature=0.2, system_prompt="")
    await structured.execute_local_project_role(p, a, "Synthetic role")
    assert observed == [4]
