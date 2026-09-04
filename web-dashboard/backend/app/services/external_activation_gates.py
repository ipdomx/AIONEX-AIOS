"""Truthful read-only ledger for external activation boundaries.

The Phase 36 registry names facts that cannot be fabricated by local source work
(provider funding, legal certification, physical-device acceptance, public media
capacity, etc.).  This module makes those boundaries operationally visible to the
Super Owner without introducing a generic "mark passed" escape hatch.

Apple platform publication / direct Apple Pay are intentionally excluded from the
current closeout scope by Owner decision.  The source registry remains truthful;
exclusion affects the current completion view only and never rewrites history.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.phase36_program import phase36_program_snapshot
from app.core.config import settings
from app.db.models import AIProvider, OwnerControlRecord
from app.services import billing
from app.services.project_ai_launch_models import LAUNCH_ENABLED_MODELS
from app.services.provider_credit_alerts import PROVIDER_FINANCE_DOMAIN

GateStatus = Literal[
    "satisfied_runtime",
    "enforced_internal_external_pending",
    "blocked_external",
    "excluded_current_scope",
]

STORE_GATE = "store-signing-and-publication"
EXCLUDED_NON_REGISTRY_BOUNDARIES = (
    "direct-apple-pay",
    "app-store-publication",
    "google-play-publication",
)


@dataclass(frozen=True, slots=True)
class GateDefinition:
    gate_id: str
    status_without_live_evidence: GateStatus
    external_fact: str
    evidence_requirements: tuple[str, ...]
    internal_controls: tuple[str, ...] = ()


_DEFINITIONS: tuple[GateDefinition, ...] = (
    GateDefinition(
        "explicit-consent-egress-runtime-acceptance",
        "enforced_internal_external_pending",
        "A bounded public egress/recording acceptance with explicit consent preserved end to end.",
        (
            "public egress runtime",
            "all-active-participant explicit consent evidence",
            "successful bounded egress acceptance",
        ),
        (
            "all-participant recording consent is fail-closed",
            "consent digest/version/timestamp evidence is generated locally",
        ),
    ),
    GateDefinition(
        "jurisdictional-healthcare-compliance-certification",
        "blocked_external",
        "A jurisdiction-specific healthcare compliance certification or approved deployment authority.",
        (
            "target jurisdiction",
            "applicable healthcare/privacy certification or legal deployment approval",
        ),
        (
            "healthcare blueprint is non-diagnostic",
            "autonomous high-stakes decisions are fail-closed",
            "human review and pseudonymous evidence controls are implemented",
        ),
    ),
    GateDefinition(
        "live-payment-provider-credential",
        "blocked_external",
        "At least one verified live payment provider credential set.",
        ("live provider credentials", "verified webhook authority"),
        ("provider readiness rejects incomplete credentials and wrong Stripe mode",),
    ),
    GateDefinition(
        "music-rights-and-ai-generated-disclosure",
        "enforced_internal_external_pending",
        "Per-use commercial music rights plus AI-generated-content disclosure evidence.",
        (
            "commercial-use authorization",
            "provider terms acceptance",
            "AI-generated disclosure acceptance",
        ),
        (
            "Stable Audio and Open Song requests enforce rights/disclosure fields",
            "missing disclosure fails closed before provider execution",
        ),
    ),
    GateDefinition(
        "music-rights-and-synthid-disclosure",
        "enforced_internal_external_pending",
        "Per-use music rights plus required SynthID/AI disclosure evidence.",
        (
            "commercial-use authorization",
            "provider terms acceptance",
            "SynthID/AI disclosure obligation",
        ),
        (
            "Lyria runtime persists SynthID and AI disclosure requirements",
            "vocal rights require checksum-bound evidence",
        ),
    ),
    GateDefinition(
        "owner-provider-funded-credit-thresholds",
        "blocked_external",
        "Truthful funded-credit baselines and low/critical thresholds for each paid launch provider.",
        (
            "current funded-credit amount per paid provider",
            "low-balance threshold",
            "critical-balance threshold",
        ),
        (
            "durable provider-finance records and low/critical alerting are implemented",
            "values cannot be inferred from usage or fabricated",
        ),
    ),
    GateDefinition(
        "physical-device-or-chain-deployment-authority",
        "blocked_external",
        "Authority and a real target for physical-device or blockchain deployment.",
        ("target device/network", "deployment authority", "physical/chain acceptance evidence"),
        ("local IoT/robotics/smart-contract source generation remains non-deploying by default",),
    ),
    GateDefinition(
        "platform-code-signing",
        "blocked_external",
        "Platform-specific trusted code-signing identity for desktop release artifacts.",
        ("target platform", "trusted signing identity/certificate", "signed artifact verification"),
        ("project builder retains platform-code-signing as a release gate",),
    ),
    GateDefinition(
        "provider-rendered-podcast-jingle-runtime-evidence",
        "blocked_external",
        "A bounded real provider render for podcast/jingle/narration output.",
        ("approved provider route", "bounded runtime acceptance", "artifact QA/cleanup evidence"),
        ("source pipeline is built but persistent paid execution is not auto-armed",),
    ),
    GateDefinition(
        "public-stun-turn-and-sfu-capacity",
        "blocked_external",
        "Public STUN/TURN and SFU capacity reachable from real external clients.",
        (
            "public STUN/TURN endpoints",
            "SFU deployment and credentials",
            "external-client capacity/latency acceptance",
        ),
        (
            "provider-neutral SFU/TURN contracts validate secret references and candidates",
            "LiveKit/Coturn/Egress images are digest-pinned in source contracts",
        ),
    ),
    GateDefinition(
        "recording-retention-and-studio-ingestion-runtime-evidence",
        "enforced_internal_external_pending",
        "A real recording lifecycle proving retention/deletion and Studio ingestion.",
        (
            "public recording/egress runtime",
            "retention/deletion evidence",
            "Studio ingestion acceptance",
        ),
        (
            "recording consent/provenance contracts are implemented",
            "resilience contract preserves consent and provenance across failover",
        ),
    ),
    GateDefinition(
        "sector-evidence-and-human-review",
        "enforced_internal_external_pending",
        "Sector-specific evidence authority and an appropriately qualified human reviewer.",
        ("sector evidence sources", "qualified reviewer authority", "review decision evidence"),
        (
            "professional evidence is checksum-bound and pseudonymous",
            "high-stakes outputs cannot become autonomous decisions",
        ),
    ),
    GateDefinition(
        STORE_GATE,
        "excluded_current_scope",
        "Mobile store signing/publication authority.",
        ("store account", "signing identity", "publication approval"),
        ("excluded from current closeout scope by Owner decision",),
    ),
    GateDefinition(
        "synthetic-voice-disclosure",
        "enforced_internal_external_pending",
        "User-facing disclosure that generated speech/dubbing uses a synthetic voice.",
        ("synthetic-voice disclosure presented/accepted for the applicable experience",),
        (
            "stock dubbing runtime marks synthetic_voice_disclosure_required=true",
            "stock voice paths do not claim identity cloning",
        ),
    ),
    GateDefinition(
        "voice-rights-and-consent-evidence",
        "blocked_external",
        "Rights/consent evidence from the voice owner or authorized subject for transformation/cloning.",
        ("voice-owner consent", "permitted use scope", "durable evidence reference"),
        ("voice transformation remains unavailable without the rights gate",),
    ),
    GateDefinition(
        "xr-device-validation",
        "blocked_external",
        "Physical XR device/session acceptance on a supported headset or mobile XR target.",
        ("physical XR device", "real session acceptance", "render/input/performance evidence"),
        ("WebXR source and browser-local delivery are already locally executed",),
    ),
)
_DEFINITION_BY_ID = {item.gate_id: item for item in _DEFINITIONS}


def _registry_gate_usage() -> dict[str, dict[str, list[str]]]:
    snapshot = phase36_program_snapshot()
    usage: dict[str, dict[str, set[str]]] = {}
    for batch in cast(list[dict[str, Any]], snapshot["batches"]):
        batch_id = str(batch["batch_id"])
        for capability in cast(list[dict[str, Any]], batch["capabilities"]):
            capability_id = str(capability["capability_id"])
            for raw_gate in capability.get("external_gates", ()):  # type: ignore[union-attr]
                gate = str(raw_gate)
                bucket = usage.setdefault(gate, {"capability_ids": set(), "batch_ids": set()})
                bucket["capability_ids"].add(capability_id)
                bucket["batch_ids"].add(batch_id)
    return {
        gate: {
            "capability_ids": sorted(values["capability_ids"]),
            "batch_ids": sorted(values["batch_ids"]),
        }
        for gate, values in usage.items()
    }


def catalog_invariant() -> dict[str, list[str]]:
    registry = set(_registry_gate_usage())
    defined = set(_DEFINITION_BY_ID)
    return {
        "missing_definitions": sorted(registry - defined),
        "orphan_definitions": sorted(defined - registry),
    }


def _live_payment_evidence() -> dict[str, Any]:
    providers = billing.provider_readiness()
    live_ready = sorted(
        item["id"]
        for item in providers
        if item.get("configured") is True
        and item.get("status") == "ready"
        and item.get("mode") == "live"
        and item.get("id") != "manual"
    )
    return {
        "environment": settings.PAYMENTS_ENVIRONMENT.strip().lower(),
        "live_ready_providers": live_ready,
        "satisfied": bool(live_ready),
        "stores_card_data": False,
    }


async def _provider_finance_evidence(session: AsyncSession) -> dict[str, Any]:
    paid_provider_types = sorted(
        {
            item.provider_type
            for item in LAUNCH_ENABLED_MODELS
            if item.provider_type != "ollama"
        }
    )
    providers = list(
        (
            await session.scalars(
                select(AIProvider).where(
                    AIProvider.organization_id
                    == settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID,
                    AIProvider.type.in_(paid_provider_types),
                    AIProvider.status == "connected",
                )
            )
        ).all()
    )
    provider_ids = {item.id for item in providers}
    configured_ids = set(
        (
            await session.scalars(
                select(OwnerControlRecord.resource_id).where(
                    OwnerControlRecord.domain == PROVIDER_FINANCE_DOMAIN,
                    OwnerControlRecord.status == "active",
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.resource_id.in_(provider_ids),
                )
            )
        ).all()
    ) if provider_ids else set()
    missing = sorted(item.type for item in providers if item.id not in configured_ids)
    return {
        "connected_paid_provider_types": sorted(item.type for item in providers),
        "configured_finance_records": len(configured_ids),
        "required_finance_records": len(provider_ids),
        "missing_provider_types": missing,
        "satisfied": bool(provider_ids) and not missing,
    }


async def external_activation_snapshot(session: AsyncSession) -> dict[str, Any]:
    invariant = catalog_invariant()
    if invariant["missing_definitions"] or invariant["orphan_definitions"]:
        raise RuntimeError("external activation gate catalog drift detected")

    usage = _registry_gate_usage()
    payment = _live_payment_evidence()
    finance = await _provider_finance_evidence(session)
    gates: list[dict[str, Any]] = []

    for definition in _DEFINITIONS:
        live_evidence: dict[str, Any] = {}
        status = definition.status_without_live_evidence
        if definition.gate_id == "live-payment-provider-credential":
            live_evidence = payment
            if payment["satisfied"]:
                status = "satisfied_runtime"
        elif definition.gate_id == "owner-provider-funded-credit-thresholds":
            live_evidence = finance
            if finance["satisfied"]:
                status = "satisfied_runtime"

        refs = usage[definition.gate_id]
        gates.append(
            {
                "gate_id": definition.gate_id,
                "status": status,
                "excluded_from_current_scope": status == "excluded_current_scope",
                "capability_ids": refs["capability_ids"],
                "batch_ids": refs["batch_ids"],
                "external_fact": definition.external_fact,
                "evidence_requirements": list(definition.evidence_requirements),
                "internal_controls": list(definition.internal_controls),
                "live_evidence": live_evidence,
            }
        )

    in_scope = [item for item in gates if not item["excluded_from_current_scope"]]
    counts = {
        "registry_gates": len(gates),
        "in_scope_gates": len(in_scope),
        "excluded_current_scope": sum(item["excluded_from_current_scope"] for item in gates),
        "satisfied_runtime": sum(item["status"] == "satisfied_runtime" for item in in_scope),
        "enforced_internal_external_pending": sum(
            item["status"] == "enforced_internal_external_pending" for item in in_scope
        ),
        "blocked_external": sum(item["status"] == "blocked_external" for item in in_scope),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope_policy": {
            "store_publication_excluded": True,
            "direct_apple_pay_excluded": True,
            "non_registry_exclusions": list(EXCLUDED_NON_REGISTRY_BOUNDARIES),
        },
        "counts": counts,
        "gates": gates,
        "catalog_invariant": invariant,
    }
