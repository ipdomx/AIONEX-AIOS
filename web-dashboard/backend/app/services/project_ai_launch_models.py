"""Reviewed Phase 36C launch model policy.

The launch policy is intentionally small and explicit.  It separates reviewed
capability/pricing/rate policy from credential-specific live inventory evidence.
A model is never routable merely because it appears here: the provider evidence
authority must also prove the exact model ID against the current provider account.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.services.provider_model_evidence import ProviderModelValidationSpec

LAUNCH_MODEL_POLICY_VERSION: Final[str] = "phase36c-launch100-model-policy-v2"


@dataclass(frozen=True, slots=True)
class LaunchModelChoice:
    provider_type: str
    model: str
    access_class: str
    priority: int
    spec: ProviderModelValidationSpec
    official_source: str
    desired_current: bool = False


# Neutral routing scores below are conservative internal policy values; they are
# not represented as provider benchmark claims.  Prices/capabilities/context are
# reviewed from the cited official provider sources and must still be combined
# with fresh live inventory evidence before persistence/routing.
FREE_OLLAMA_GEMMA3 = LaunchModelChoice(
    provider_type="ollama",
    model="gemma3:4b",
    access_class="free",
    priority=100,
    official_source="https://ollama.com/library/gemma3",
    spec=ProviderModelValidationSpec(
        provider_type="ollama",
        model="gemma3:4b",
        tasks=frozenset({"reasoning", "research", "coding", "review"}),
        policy_ref=f"{LAUNCH_MODEL_POLICY_VERSION}:ollama:gemma3-4b",
        languages=frozenset({"multilingual"}),
        supports_tools=False,
        supports_vision=True,
        supports_audio=False,
        local=True,
        max_context_tokens=128_000,
        quality_score=0.50,
        latency_score=0.50,
        privacy_score=1.0,
        input_cost_per_million=0.0,
        output_cost_per_million=0.0,
        requests_per_minute=120,
        concurrent_requests=2,
        circuit_failure_threshold=3,
        circuit_failure_window_seconds=60,
        circuit_open_seconds=30,
        lease_seconds=120,
    ),
)

PAID_MISTRAL_MEDIUM_35 = LaunchModelChoice(
    provider_type="mistral",
    model="mistral-medium-3-5",
    access_class="paid",
    priority=100,
    official_source="https://docs.mistral.ai/models/model-cards/mistral-medium-3-5-26-04",
    spec=ProviderModelValidationSpec(
        provider_type="mistral",
        model="mistral-medium-3-5",
        tasks=frozenset({"reasoning", "research", "coding", "review"}),
        policy_ref=f"{LAUNCH_MODEL_POLICY_VERSION}:mistral:medium-3-5",
        languages=frozenset({"multilingual"}),
        supports_tools=True,
        supports_vision=True,
        supports_audio=False,
        local=False,
        max_context_tokens=256_000,
        quality_score=0.75,
        latency_score=0.65,
        privacy_score=0.50,
        input_cost_per_million=1.50,
        output_cost_per_million=7.50,
        # Internal launch caps; not claimed as the provider account limits.
        requests_per_minute=60,
        concurrent_requests=4,
        circuit_failure_threshold=3,
        circuit_failure_window_seconds=60,
        circuit_open_seconds=30,
        lease_seconds=120,
    ),
)

PAID_DEEPSEEK_V4_PRO = LaunchModelChoice(
    provider_type="deepseek",
    model="deepseek-v4-pro",
    access_class="paid",
    priority=90,
    official_source="https://api-docs.deepseek.com/quick_start/pricing",
    spec=ProviderModelValidationSpec(
        provider_type="deepseek",
        model="deepseek-v4-pro",
        tasks=frozenset({"reasoning", "research", "coding", "review"}),
        policy_ref=f"{LAUNCH_MODEL_POLICY_VERSION}:deepseek:v4-pro",
        languages=frozenset({"multilingual"}),
        supports_tools=True,
        supports_vision=False,
        supports_audio=False,
        local=False,
        max_context_tokens=1_000_000,
        quality_score=0.72,
        latency_score=0.70,
        privacy_score=0.50,
        # Conservative cache-miss input price is used for budgeting.
        input_cost_per_million=0.435,
        output_cost_per_million=0.87,
        # Deliberately below documented provider concurrency to protect launch.
        requests_per_minute=120,
        concurrent_requests=6,
        circuit_failure_threshold=3,
        circuit_failure_window_seconds=60,
        circuit_open_seconds=30,
        lease_seconds=120,
    ),
)

# OpenAI GPT-5.6 is the reviewed current generation.  It is launch-eligible only
# when credential-specific inventory evidence proves the exact ID; evidence TTL
# still fails closed if provider availability later changes.
OPENAI_DESIRED_CURRENT = (
    LaunchModelChoice(
        provider_type="openai",
        model="gpt-5.6-sol",
        access_class="paid",
        priority=80,
        desired_current=True,
        official_source="https://developers.openai.com/api/docs/models",
        spec=ProviderModelValidationSpec(
            provider_type="openai",
            model="gpt-5.6-sol",
            tasks=frozenset({"reasoning", "research", "coding", "review"}),
            policy_ref=f"{LAUNCH_MODEL_POLICY_VERSION}:openai:gpt-5.6-sol",
            languages=frozenset({"multilingual"}),
            supports_tools=True,
            supports_vision=True,
            supports_audio=False,
            local=False,
            max_context_tokens=1_050_000,
            quality_score=0.90,
            latency_score=0.60,
            privacy_score=0.50,
            input_cost_per_million=5.0,
            output_cost_per_million=30.0,
            requests_per_minute=60,
            concurrent_requests=4,
            circuit_failure_threshold=3,
            circuit_failure_window_seconds=60,
            circuit_open_seconds=30,
            lease_seconds=120,
        ),
    ),
    LaunchModelChoice(
        provider_type="openai",
        model="gpt-5.6-terra",
        access_class="paid",
        priority=85,
        desired_current=True,
        official_source="https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        spec=ProviderModelValidationSpec(
            provider_type="openai",
            model="gpt-5.6-terra",
            tasks=frozenset({"reasoning", "research", "coding", "review"}),
            policy_ref=f"{LAUNCH_MODEL_POLICY_VERSION}:openai:gpt-5.6-terra",
            languages=frozenset({"multilingual"}),
            supports_tools=True,
            supports_vision=True,
            supports_audio=False,
            local=False,
            max_context_tokens=1_050_000,
            quality_score=0.85,
            latency_score=0.70,
            privacy_score=0.50,
            input_cost_per_million=2.0,
            output_cost_per_million=12.0,
            requests_per_minute=60,
            concurrent_requests=4,
            circuit_failure_threshold=3,
            circuit_failure_window_seconds=60,
            circuit_open_seconds=30,
            lease_seconds=120,
        ),
    ),
    LaunchModelChoice(
        provider_type="openai",
        model="gpt-5.6-luna",
        access_class="paid",
        priority=75,
        desired_current=True,
        official_source="https://developers.openai.com/api/docs/models/gpt-5.6-luna",
        spec=ProviderModelValidationSpec(
            provider_type="openai",
            model="gpt-5.6-luna",
            tasks=frozenset({"reasoning", "research", "coding", "review"}),
            policy_ref=f"{LAUNCH_MODEL_POLICY_VERSION}:openai:gpt-5.6-luna",
            languages=frozenset({"multilingual"}),
            supports_tools=True,
            supports_vision=True,
            supports_audio=False,
            local=False,
            max_context_tokens=1_050_000,
            quality_score=0.78,
            latency_score=0.80,
            privacy_score=0.50,
            input_cost_per_million=0.20,
            output_cost_per_million=1.20,
            requests_per_minute=60,
            concurrent_requests=4,
            circuit_failure_threshold=3,
            circuit_failure_window_seconds=60,
            circuit_open_seconds=30,
            lease_seconds=120,
        ),
    ),
)

LAUNCH_ENABLED_MODELS: Final[tuple[LaunchModelChoice, ...]] = (
    FREE_OLLAMA_GEMMA3,
    *OPENAI_DESIRED_CURRENT,
    PAID_MISTRAL_MEDIUM_35,
    PAID_DEEPSEEK_V4_PRO,
)

VALIDATED_MODEL_TTL: Final[timedelta] = timedelta(hours=6)


def launch_models_for(access_class: str) -> tuple[LaunchModelChoice, ...]:
    normalized = access_class.strip().lower()
    return tuple(item for item in LAUNCH_ENABLED_MODELS if item.access_class == normalized)


def desired_current_models() -> tuple[LaunchModelChoice, ...]:
    return LAUNCH_ENABLED_MODELS
