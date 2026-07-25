from __future__ import annotations

import asyncio

from aios.providers import DataSensitivity, ModelRequest, ModelResponse, MultiModelPlatform
from aios.providers.integration import AIInteractionJournal, AIProviderIntegration, AIWorkItem, PromptContextFirewall
from aios.providers.routing import AIRoutingLayer, ExecutionMode, RoutingPolicy


async def _transport(request: ModelRequest, model: str) -> ModelResponse:
    return ModelResponse(
        provider="ollama",
        model=model,
        text="ok:" + request.prompt,
        input_tokens=5,
        output_tokens=3,
        latency_ms=12.0,
        cost=0.0,
        confidence=0.91,
    )


def test_firewall_redacts_secrets():
    request = ModelRequest(task="coding", prompt="token=super-secret-value", sensitivity=DataSensitivity.INTERNAL)
    sanitized, findings = PromptContextFirewall().sanitize(request)
    assert "super-secret-value" not in sanitized.prompt
    assert "secret-redacted" in findings


def test_final_integration_executes_and_journals(tmp_path):
    platform = MultiModelPlatform({"ollama": _transport})
    routing = AIRoutingLayer(platform)
    integration = AIProviderIntegration(platform, routing, tmp_path / "ai-provider-ledger.jsonl")
    policy = RoutingPolicy(execution=ExecutionMode.SINGLE, offline_only=True, max_models=1)
    item = AIWorkItem(
        task_id="task-1",
        request=ModelRequest(task="coding", prompt="build module", require_local=True),
        policy=policy,
        project="demo",
    )
    result = asyncio.run(integration.execute(item))
    assert result.provider == "ollama"
    assert result.text == "ok:build module"
    assert integration.journal.verify() is True
    assert integration.health()["providers"] >= 5


def test_journal_detects_tampering(tmp_path):
    journal = AIInteractionJournal(tmp_path / "ledger.jsonl")
    journal.append({"event": "one"})
    journal.append({"event": "two"})
    assert journal.verify() is True
    path = tmp_path / "ledger.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace('"event": "one"', '"event": "changed"'), encoding="utf-8")
    assert journal.verify() is False
