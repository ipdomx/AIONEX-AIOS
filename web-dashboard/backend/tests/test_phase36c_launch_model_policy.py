"""Phase 36C reviewed launch-model policy contracts."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.project_ai_launch_models import (
    FREE_OLLAMA_GEMMA3,
    LAUNCH_ENABLED_MODELS,
    LAUNCH_MODEL_POLICY_VERSION,
    OPENAI_DESIRED_CURRENT,
    PAID_DEEPSEEK_V4_PRO,
    PAID_MISTRAL_MEDIUM_35,
    launch_models_for,
)
from app.services.provider_model_evidence import (
    ProviderModelEvidenceError,
    ProviderModelInventoryEvidence,
    build_validated_model_from_inventory,
)


def _inventory(provider: str, model_ids: tuple[str, ...]) -> ProviderModelInventoryEvidence:
    return ProviderModelInventoryEvidence(
        provider_id=f"provider-{provider}",
        provider_type=provider,
        model_ids=model_ids,
        evidence_ref=f"test:inventory:{provider}",
        observed_at=datetime.now(UTC),
        latency_ms=1.0,
    )


def test_launch_policy_free_is_local_zero_cost_and_paid_is_current_reviewed_set() -> None:
    free = launch_models_for("free")
    paid = launch_models_for("paid")
    assert [item.model for item in free] == ["gemma3:4b"]
    assert free[0].spec.local is True
    assert free[0].spec.input_cost_per_million == 0
    assert free[0].spec.output_cost_per_million == 0
    assert {item.model for item in paid} == {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "mistral-medium-3-5",
        "deepseek-v4-pro",
    }
    assert all(item.spec.local is False for item in paid)
    assert all("default" not in item.model.lower() for item in LAUNCH_ENABLED_MODELS)


def test_reviewed_specs_match_current_provider_capability_and_pricing_policy() -> None:
    assert PAID_MISTRAL_MEDIUM_35.spec.max_context_tokens == 256_000
    assert PAID_MISTRAL_MEDIUM_35.spec.supports_tools is True
    assert PAID_MISTRAL_MEDIUM_35.spec.input_cost_per_million == 1.5
    assert PAID_MISTRAL_MEDIUM_35.spec.output_cost_per_million == 7.5
    assert PAID_DEEPSEEK_V4_PRO.spec.max_context_tokens == 1_000_000
    assert PAID_DEEPSEEK_V4_PRO.spec.supports_tools is True
    assert PAID_DEEPSEEK_V4_PRO.spec.input_cost_per_million == 0.435
    assert PAID_DEEPSEEK_V4_PRO.spec.output_cost_per_million == 0.87
    assert FREE_OLLAMA_GEMMA3.spec.max_context_tokens == 128_000
    assert FREE_OLLAMA_GEMMA3.spec.supports_tools is False
    assert LAUNCH_MODEL_POLICY_VERSION == "phase36c-launch100-model-policy-v2"
    openai = {item.model: item for item in OPENAI_DESIRED_CURRENT}
    assert openai["gpt-5.6-sol"].spec.input_cost_per_million == 5.0
    assert openai["gpt-5.6-sol"].spec.output_cost_per_million == 30.0
    assert openai["gpt-5.6-terra"].spec.input_cost_per_million == 2.0
    assert openai["gpt-5.6-terra"].spec.output_cost_per_million == 12.0
    assert openai["gpt-5.6-luna"].spec.input_cost_per_million == 0.20
    assert openai["gpt-5.6-luna"].spec.output_cost_per_million == 1.20


def test_fresh_inventory_can_validate_launch_models_but_absent_model_fails_closed() -> None:
    mistral_inventory = _inventory("mistral", ("mistral-medium-3-5", "other"))
    entry = build_validated_model_from_inventory(
        mistral_inventory,
        PAID_MISTRAL_MEDIUM_35.spec,
        now=mistral_inventory.observed_at,
    )
    assert entry["model"] == "mistral-medium-3-5"
    assert entry["input_cost_per_million"] == 1.5
    with pytest.raises(ProviderModelEvidenceError, match="absent"):
        build_validated_model_from_inventory(
            _inventory("mistral", ("other",)),
            PAID_MISTRAL_MEDIUM_35.spec,
        )


def test_openai_current_family_requires_credential_inventory_before_validation() -> None:
    assert {item.model for item in OPENAI_DESIRED_CURRENT} == {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    }
    assert all(item.desired_current for item in OPENAI_DESIRED_CURRENT)
    assert {item.model for item in OPENAI_DESIRED_CURRENT}.issubset(
        {item.model for item in LAUNCH_ENABLED_MODELS}
    )
    fresh = _inventory(
        "openai",
        ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
    )
    for choice in OPENAI_DESIRED_CURRENT:
        entry = build_validated_model_from_inventory(fresh, choice.spec, now=fresh.observed_at)
        assert entry["model"] == choice.model
    absent = _inventory("openai", ("gpt-4.1", "chat-latest"))
    for choice in OPENAI_DESIRED_CURRENT:
        with pytest.raises(ProviderModelEvidenceError, match="absent"):
            build_validated_model_from_inventory(absent, choice.spec)
