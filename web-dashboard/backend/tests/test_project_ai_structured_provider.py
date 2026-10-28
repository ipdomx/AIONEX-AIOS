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
        assert request["options"]["temperature"] == 0.0
        assert request["format"] == ControlledProjectBuilder._schema()
        assert request["stream"] is False
    else:
        assert request["store"] is False
        assert request["max_output_tokens"] == 3072
        assert request["text"]["format"]["strict"] is True
        assert request["text"]["format"]["schema"] == ControlledProjectBuilder._schema()


@pytest.mark.anyio
@pytest.mark.parametrize("tokens", [None, 0, 255, 4097, True, "3072"])
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
@pytest.mark.parametrize("role", ["planner", "researcher", "reviewer"])
async def test_bounded_local_project_role_applies_exact_task_token_limit(
    monkeypatch: pytest.MonkeyPatch, role: str,
) -> None:
    request: dict = {}

    async def real_interface_stub(method, url, **kwargs):
        assert method == "POST" and url == "http://127.0.0.1:11434/api/chat"
        assert kwargs["timeout"] <= 65
        request.update(kwargs["json_body"])
        return {
            "model": "qwen2.5:1.5b",
            "message": {"content": "Reviewed project role notes"},
            "prompt_eval_count": 30,
            "eval_count": 192,
        }, 7420.0

    monkeypatch.setattr(structured, "_request_json", real_interface_stub)
    provider = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="qwen2.5:1.5b", temperature=0.2, system_prompt="")
    result = await structured.execute_bounded_project_ollama_role(
        provider, agent, f"Synthetic {role} role only",
        task_max_tokens=192,
    )
    assert result["provider"] == "ollama"
    assert result["usage"]["output_tokens"] == 192
    assert result["usage"]["total_tokens"] == 222
    assert request["options"]["num_predict"] == 192
    assert request["options"]["num_ctx"] == 4096
    assert request["options"]["num_thread"] == 6
    assert request["stream"] is False
    assert request["keep_alive"] == "2m"
    assert len(request["messages"]) == 1
    assert "format" not in request


@pytest.mark.anyio
@pytest.mark.parametrize("tokens", [None, 0, 15, 257, True, "192"])
async def test_local_role_invalid_token_budget_fails_without_model_call(
    monkeypatch: pytest.MonkeyPatch, tokens,
) -> None:
    called = False

    async def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("unexpected model request")

    monkeypatch.setattr(structured, "_request_json", forbidden)
    provider = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="qwen2.5:1.5b", temperature=0.2, system_prompt="")
    with pytest.raises(HTTPException) as error:
        await structured.execute_bounded_project_ollama_role(
            provider, agent, "Bounded planner",
            task_max_tokens=tokens,
        )
    assert error.value.status_code == 422
    assert called is False


@pytest.mark.anyio
async def test_ollama_local_role_rejects_usage_overrun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forged(_method, _url, **_kwargs):
        return {"message": {"content": "bad"},
                "prompt_eval_count": 10,"eval_count": 400}, 1.0

    monkeypatch.setattr(structured, "_request_json", forged)
    provider = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="qwen2.5:1.5b", temperature=0.2, system_prompt="")
    with pytest.raises(HTTPException) as error:
        await structured.execute_bounded_project_ollama_role(
            provider, agent, "Bounded reviewer", task_max_tokens=192,
        )
    assert error.value.status_code == 502



@pytest.mark.anyio
async def test_local_compact_coder_is_bounded_to_640_not_general_chat_1024(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The proven Qwen compact brief is a bounded 640-token inference contract."""
    sent = {}
    async def stub(_method, _url, **kwargs):
        sent.update(kwargs["json_body"])
        assert kwargs["timeout"] == 90
        return {
            "model": "qwen2.5:1.5b",
            "message": {"content": '{"kind":"aionex.compact-project.v1"}'},
            "prompt_eval_count": 210,
            "eval_count": 181,
        }, 7420.0
    from aios.project_ai_compact_spec import compact_project_schema
    monkeypatch.setattr(structured, "_request_json", stub)
    p = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    a = SimpleNamespace(model="qwen2.5:1.5b", system_prompt="", temperature=0.0)
    result = await structured.execute_structured_project_coder(
        p, a, "Synthetic local compact project only",
        project_coder_max_tokens=640,
        project_coder_schema=compact_project_schema(),
    )
    assert result["model"] == "qwen2.5:1.5b"
    assert result["usage"]["output_tokens"] == 181
    assert sent["options"]["num_predict"] == 640
    assert sent["options"]["num_thread"] == 6
    assert sent["options"]["num_ctx"] == 4096
    assert sent["keep_alive"] == "2m"
