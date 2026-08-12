"""Truthful durable provider/model completion contracts."""
from __future__ import annotations

from pathlib import Path

from app.core.ai_runtime import FINAL_SUPPORTED_PROVIDER_TYPES, provider_models
from app.services import ai_runtime_service

ROOT = Path(__file__).resolve().parents[1]


def test_phase29j_supported_provider_types_are_final_contract() -> None:
    assert set(FINAL_SUPPORTED_PROVIDER_TYPES) == {
        "openai", "anthropic", "gemini", "openrouter", "ollama", "mistral",
        "cohere", "xai", "deepseek", "groq", "together", "fireworks",
        "huggingface", "azure_openai", "aws_bedrock", "tripo3d", "meshy",
    }
    assert set(ai_runtime_service.SUPPORTED_PROVIDER_TYPES) == set(FINAL_SUPPORTED_PROVIDER_TYPES)


def test_model_catalog_is_truthful_and_provider_scoped() -> None:
    assert provider_models("openai")
    assert provider_models("ollama")[0]["local"] is True
    assert provider_models("does-not-exist") == []


def test_runtime_business_state_is_not_process_local() -> None:
    core = (ROOT / "app/core/ai_runtime.py").read_text(encoding="utf-8")
    service = (ROOT / "app/services/ai_runtime_service.py").read_text(encoding="utf-8")
    agents = (ROOT / "app/api/v1/endpoints/ai_agents.py").read_text(encoding="utf-8")
    providers = (ROOT / "app/api/v1/endpoints/ai_providers.py").read_text(encoding="utf-8")
    assert "AIRuntimeState" not in core
    assert "self.providers" not in core
    assert "self.agents" not in core
    assert "SessionLocal" in service
    assert "select(AIAgent" in service
    assert "select(AIProvider" in service
    assert "ai_runtime_service" in agents
    assert "ai_runtime_service" in providers


def test_provider_keys_are_encrypted_and_never_returned_by_snapshot() -> None:
    ciphertext = ai_runtime_service.encrypt_provider_secret("secret-value-1234")
    assert ciphertext.startswith("fernet:v1:")
    assert "secret-value-1234" not in ciphertext
    assert ai_runtime_service.decrypt_provider_secret(ciphertext) == "secret-value-1234"
    source = (ROOT / "app/services/ai_runtime_service.py").read_text(encoding="utf-8")
    snapshot = source[source.index("def provider_snapshot"):source.index("def agent_snapshot")]
    assert "encrypted_api_key" not in snapshot


def test_provider_execution_has_no_synthetic_success_path() -> None:
    source = (ROOT / "app/services/ai_runtime_service.py").read_text(encoding="utf-8")
    assert "Execution accepted by" not in source
    assert "/v1/responses" in source
    assert "/v1/messages" in source
    assert ":generateContent" in source
    assert 'return f"{base}/api/v1"' in source
    assert "/v2/chat" in source
    assert 'return f"{base}/openai/v1"' in source
    assert "bedrock-runtime" in source
    assert ".converse(" in source
    assert "/api/chat" in source


def test_provider_test_endpoint_restores_configured_state_after_external_gate() -> None:
    source = (ROOT / "app/api/v1/endpoints/ai_providers.py").read_text(encoding="utf-8")
    assert 'result["status"] in {"configured", "disabled", "unconfigured"}' in source
    assert 'provider.status = result["status"]' in source
