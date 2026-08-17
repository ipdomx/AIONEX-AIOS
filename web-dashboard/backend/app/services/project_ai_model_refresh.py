"""Refresh reviewed Phase 36C launch model evidence from provider inventories."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AIProvider, AuditEvent
from app.services import communications
from app.services.lifecycle_alerts import owner_alert_channels
from app.services.project_ai_launch_models import (
    LAUNCH_ENABLED_MODELS,
    VALIDATED_MODEL_TTL,
)
from app.services.provider_model_evidence import (
    ProviderModelEvidenceError,
    Requester,
    _request_json,
    build_validated_model_from_inventory,
    persist_provider_validated_model,
    probe_provider_model_inventory,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def _revoke_missing_model(
    session: AsyncSession,
    provider: AIProvider,
    *,
    model: str,
    actor_id: str | None,
) -> bool:
    config = dict(provider.config or {})
    rows = config.get("validated_models")
    if not isinstance(rows, list):
        return False
    retained = [
        dict(item)
        for item in rows
        if isinstance(item, dict) and str(item.get("model") or "") != model
    ]
    if len(retained) == len(rows):
        return False
    config["validated_models"] = retained
    provider.config = config
    session.add(
        AuditEvent(
            organization_id=provider.organization_id,
            user_id=actor_id,
            action="provider.model_evidence.revoked_missing_inventory",
            resource_type="ai_provider",
            resource_id=provider.id,
            details={"provider": provider.type, "model": model},
        )
    )
    await session.flush()
    return True


async def _notify_missing_model(
    session: AsyncSession,
    provider: AIProvider,
    *,
    model: str,
) -> list:
    day = _now().strftime("%Y%m%d")
    return await communications.notify_audience(
        session,
        organization_id=provider.organization_id,
        audience="platform_owner",
        event_key="project_ai.provider_model.current_unavailable",
        category="ai",
        title="Current AI model is unavailable on the provider account",
        message=(
            f"Provider {provider.type} does not currently expose reviewed launch model {model} "
            "to the configured credential. Routing stays blocked for that model until fresh evidence proves availability."
        ),
        severity="warning",
        channels=owner_alert_channels(),
        source_type="ai_provider",
        source_id=provider.id,
        correlation_id=provider.id,
        dedupe_prefix=f"project-ai-model-unavailable:{provider.id}:{model}:{day}",
        payload={"provider_id": provider.id, "provider_type": provider.type, "model": model},
        respect_preferences=False,
    )


async def refresh_launch_model_evidence(
    session: AsyncSession,
    *,
    actor_id: str | None = None,
    requester: Requester = _request_json,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    current = (observed_at or _now()).astimezone(UTC)
    by_provider: dict[str, list] = defaultdict(list)
    for choice in LAUNCH_ENABLED_MODELS:
        by_provider[choice.provider_type].append(choice)

    rows = list(
        (
            await session.scalars(
                select(AIProvider)
                .where(
                    AIProvider.organization_id
                    == settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID,
                    AIProvider.type.in_(sorted(by_provider)),
                )
                .order_by(AIProvider.type, AIProvider.id)
            )
        ).all()
    )
    provider_rows: dict[str, list[AIProvider]] = defaultdict(list)
    for provider in rows:
        provider_rows[provider.type.strip().lower()].append(provider)

    validated: list[str] = []
    unavailable: list[str] = []
    probe_failures: list[str] = []
    revoked: list[str] = []
    notifications: list = []

    for provider_type, choices in sorted(by_provider.items()):
        candidates = provider_rows.get(provider_type, [])
        if len(candidates) != 1:
            probe_failures.append(f"{provider_type}:provider-record-count-{len(candidates)}")
            continue
        provider = candidates[0]
        if provider.status != "connected":
            probe_failures.append(f"{provider_type}:not-connected")
            continue
        try:
            evidence = await probe_provider_model_inventory(
                provider,
                requester=requester,
                observed_at=current,
            )
        except ProviderModelEvidenceError:
            probe_failures.append(f"{provider_type}:probe-failed")
            continue

        inventory = set(evidence.model_ids)
        for choice in choices:
            route_key = f"{provider_type}:{choice.model}"
            if choice.model not in inventory:
                unavailable.append(route_key)
                if await _revoke_missing_model(
                    session,
                    provider,
                    model=choice.model,
                    actor_id=actor_id,
                ):
                    revoked.append(route_key)
                notifications.extend(
                    await _notify_missing_model(session, provider, model=choice.model)
                )
                continue
            entry = build_validated_model_from_inventory(
                evidence,
                choice.spec,
                now=current,
                max_evidence_age=VALIDATED_MODEL_TTL,
                ttl=VALIDATED_MODEL_TTL,
            )
            await persist_provider_validated_model(
                session,
                organization_id=provider.organization_id,
                provider_id=provider.id,
                actor_id=actor_id,
                entry=entry,
            )
            validated.append(route_key)

    session.add(
        AuditEvent(
            organization_id=settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID,
            user_id=actor_id,
            action="project_ai.launch_model_evidence.refreshed",
            resource_type="project_ai_launch_models",
            resource_id="launch100",
            details={
                "validated": sorted(validated),
                "unavailable": sorted(unavailable),
                "probe_failures": sorted(probe_failures),
                "revoked": sorted(revoked),
                "ttl_seconds": int(VALIDATED_MODEL_TTL.total_seconds()),
            },
        )
    )
    await session.flush()
    return {
        "validated": sorted(validated),
        "unavailable": sorted(unavailable),
        "probe_failures": sorted(probe_failures),
        "revoked": sorted(revoked),
        "notifications": notifications,
        "observed_at": current.isoformat(),
        "ttl_seconds": int(VALIDATED_MODEL_TTL.total_seconds()),
    }
