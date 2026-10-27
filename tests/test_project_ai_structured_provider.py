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
