"""Owner-governed AI provider credit estimates and escalation alerts.

Provider billing APIs are not assumed to exist. The Owner records the funded
credit at a top-up checkpoint; AIONEX subtracts durable, measured provider spend
from that baseline. Explicit provider billing/quota failures can also escalate
immediately without exposing credentials or provider response bodies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIProvider, OwnerControlRecord, ProjectAIRouteAttemptRecord
from app.services import communications
from app.services.lifecycle_alerts import owner_alert_channels
from app.services.project_execution_routing_durable import usd_to_microusd

PROVIDER_FINANCE_DOMAIN = "project-ai-provider-finance"


class ProviderCreditPolicyError(RuntimeError):
    """Provider credit policy cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class ProviderCreditSnapshot:
    provider_id: str
    provider_type: str
    enabled: bool
    funded_microusd: int
    baseline_spend_microusd: int
    current_spend_microusd: int
    consumed_since_topup_microusd: int
    remaining_microusd: int
    low_threshold_microusd: int
    critical_threshold_microusd: int
    policy_version: int
    funding_mode: str = "numeric"

    @property
    def balance_amount_private(self) -> bool:
        return self.funding_mode in {"owner_attested", "numeric_private"}

    @property
    def remaining_usd_internal(self) -> float:
        return round(self.remaining_microusd / 1_000_000, 6)

    @property
    def remaining_usd(self) -> float | None:
        if self.balance_amount_private:
            return None
        return self.remaining_usd_internal

    @property
    def state(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.funding_mode == "owner_attested":
            return "funded_attested"
        if self.remaining_microusd <= self.critical_threshold_microusd:
            return "critical"
        if self.remaining_microusd <= self.low_threshold_microusd:
            return "low"
        return "healthy"

    def public(self) -> dict[str, Any]:
        private_amount = self.balance_amount_private
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "enabled": self.enabled,
            "funding_mode": self.funding_mode,
            "funded_confirmed": self.enabled and self.funding_mode in {"numeric", "numeric_private", "owner_attested"},
            "balance_amount_private": private_amount,
            "funded_usd": None if private_amount else round(self.funded_microusd / 1_000_000, 6),
            "consumed_since_topup_usd": round(
                self.consumed_since_topup_microusd / 1_000_000, 6
            ),
            "remaining_usd": self.remaining_usd,
            "low_balance_threshold_usd": None if private_amount else round(
                self.low_threshold_microusd / 1_000_000, 6
            ),
            "critical_balance_threshold_usd": None if private_amount else round(
                self.critical_threshold_microusd / 1_000_000, 6
            ),
            "billing_failure_alerts_enabled": True,
            "state": self.state,
            "policy_version": self.policy_version,
        }

    def owner(self) -> dict[str, Any]:
        """Return finance data to the authenticated Super Owner only.

        ``numeric_private`` keeps amounts out of general snapshots and notification
        payloads while still allowing the Owner console to display the configured
        funded amount and thresholds needed for predictive alerts.
        """
        payload = self.public()
        if self.funding_mode == "numeric_private":
            payload.update(
                {
                    "funded_usd": round(self.funded_microusd / 1_000_000, 6),
                    "remaining_usd": self.remaining_usd_internal,
                    "low_balance_threshold_usd": round(
                        self.low_threshold_microusd / 1_000_000, 6
                    ),
                    "critical_balance_threshold_usd": round(
                        self.critical_threshold_microusd / 1_000_000, 6
                    ),
                }
            )
        return payload


def _payload_amount(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key, 0)
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise ProviderCreditPolicyError(f"{key} is invalid") from exc
    if amount < 0:
        raise ProviderCreditPolicyError(f"{key} must be non-negative")
    return amount


async def provider_total_spend_microusd(
    session: AsyncSession, provider: AIProvider
) -> int:
    route_spend = int(
        await session.scalar(
            select(func.coalesce(func.sum(ProjectAIRouteAttemptRecord.actual_microusd), 0)).where(
                ProjectAIRouteAttemptRecord.provider_id == provider.id
            )
        )
        or 0
    )
    runtime_spend = _payload_amount(dict(provider.config or {}), "runtime_spend_microusd")
    return route_spend + runtime_spend


async def configure_provider_credit(
    session: AsyncSession,
    *,
    provider_id: str,
    funded_credit_usd: float,
    low_balance_threshold_usd: float,
    critical_balance_threshold_usd: float,
    enabled: bool = True,
    balance_amount_private: bool = False,
) -> ProviderCreditSnapshot:
    provider = await session.scalar(
        select(AIProvider).where(AIProvider.id == provider_id).with_for_update()
    )
    if provider is None:
        raise ProviderCreditPolicyError("provider was not found")
    funded = usd_to_microusd(float(funded_credit_usd))
    low = usd_to_microusd(float(low_balance_threshold_usd))
    critical = usd_to_microusd(float(critical_balance_threshold_usd))
    if critical > low:
        raise ProviderCreditPolicyError("critical balance threshold cannot exceed low threshold")
    if low > funded:
        raise ProviderCreditPolicyError("low balance threshold cannot exceed funded credit")
    baseline = await provider_total_spend_microusd(session, provider)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == PROVIDER_FINANCE_DOMAIN,
            OwnerControlRecord.resource_id == provider_id,
        )
        .with_for_update()
    )
    payload = {
        "funding_mode": "numeric_private" if balance_amount_private else "numeric",
        "funded_confirmed": True,
        "balance_amount_private": bool(balance_amount_private),
        "funded_microusd": funded,
        "baseline_spend_microusd": baseline,
        "low_threshold_microusd": low,
        "critical_threshold_microusd": critical,
        "topup_recorded_at": datetime.now(UTC).isoformat(),
    }
    if record is None:
        record = OwnerControlRecord(
            domain=PROVIDER_FINANCE_DOMAIN,
            resource_id=provider_id,
            status="active",
            enabled=bool(enabled),
            payload=payload,
            version=1,
        )
        session.add(record)
    else:
        record.status = "active"
        record.enabled = bool(enabled)
        record.payload = payload
        record.version += 1
    await session.flush()
    return await provider_credit_snapshot(session, provider_id=provider_id, lock=False)


async def attest_provider_funded(
    session: AsyncSession,
    *,
    provider_id: str,
    enabled: bool = True,
) -> ProviderCreditSnapshot:
    """Record Owner-confirmed funding without inventing or exposing a balance amount.

    Some providers do not expose a supported balance API and the Owner may choose
    to keep the exact funded amount private. In this mode numeric low-balance
    estimates are intentionally unavailable; explicit billing/quota failures still
    trigger the existing fail-closed alert path.
    """
    provider = await session.scalar(
        select(AIProvider).where(AIProvider.id == provider_id).with_for_update()
    )
    if provider is None:
        raise ProviderCreditPolicyError("provider was not found")
    baseline = await provider_total_spend_microusd(session, provider)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == PROVIDER_FINANCE_DOMAIN,
            OwnerControlRecord.resource_id == provider_id,
        )
        .with_for_update()
    )
    payload = {
        "funding_mode": "owner_attested",
        "funded_confirmed": True,
        "balance_amount_private": True,
        "funded_microusd": 0,
        "baseline_spend_microusd": baseline,
        "low_threshold_microusd": 0,
        "critical_threshold_microusd": 0,
        "attested_at": datetime.now(UTC).isoformat(),
        "billing_failure_alerts_enabled": True,
    }
    if record is None:
        record = OwnerControlRecord(
            domain=PROVIDER_FINANCE_DOMAIN,
            resource_id=provider_id,
            status="active",
            enabled=bool(enabled),
            payload=payload,
            version=1,
        )
        session.add(record)
    else:
        record.status = "active"
        record.enabled = bool(enabled)
        record.payload = payload
        record.version += 1
    await session.flush()
    return await provider_credit_snapshot(session, provider_id=provider_id, lock=False)


async def provider_credit_snapshot(
    session: AsyncSession,
    *,
    provider_id: str,
    lock: bool = False,
) -> ProviderCreditSnapshot:
    provider = await session.get(AIProvider, provider_id)
    if provider is None:
        raise ProviderCreditPolicyError("provider was not found")
    statement = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == PROVIDER_FINANCE_DOMAIN,
        OwnerControlRecord.resource_id == provider_id,
        OwnerControlRecord.status == "active",
    )
    if lock:
        statement = statement.with_for_update()
    record = await session.scalar(statement)
    if record is None:
        raise ProviderCreditPolicyError("provider credit policy is not configured")
    payload = dict(record.payload or {})
    funding_mode = str(payload.get("funding_mode") or "numeric")
    if funding_mode not in {"numeric", "numeric_private", "owner_attested"}:
        raise ProviderCreditPolicyError("funding_mode is invalid")
    if funding_mode == "owner_attested" and payload.get("funded_confirmed") is not True:
        raise ProviderCreditPolicyError("owner-attested funding is not confirmed")
    funded = _payload_amount(payload, "funded_microusd")
    baseline = _payload_amount(payload, "baseline_spend_microusd")
    low = _payload_amount(payload, "low_threshold_microusd")
    critical = _payload_amount(payload, "critical_threshold_microusd")
    current = await provider_total_spend_microusd(session, provider)
    consumed = max(0, current - baseline)
    remaining = funded - consumed
    return ProviderCreditSnapshot(
        provider_id=provider.id,
        provider_type=provider.type,
        enabled=bool(record.enabled),
        funded_microusd=funded,
        baseline_spend_microusd=baseline,
        current_spend_microusd=current,
        consumed_since_topup_microusd=consumed,
        remaining_microusd=remaining,
        low_threshold_microusd=low,
        critical_threshold_microusd=critical,
        policy_version=record.version,
        funding_mode=funding_mode,
    )


async def _notify_credit_state(
    session: AsyncSession,
    snapshot: ProviderCreditSnapshot,
) -> list:
    if snapshot.state not in {"low", "critical"}:
        return []
    severity = "critical" if snapshot.state == "critical" else "warning"
    title = (
        "AI provider credit is critically low"
        if snapshot.state == "critical"
        else "AI provider credit is running low"
    )
    if snapshot.balance_amount_private:
        message = (
            f"Provider {snapshot.provider_type} estimated funded credit crossed the "
            f"{snapshot.state} threshold. Review or top up the provider before live "
            "project capacity is affected."
        )
    else:
        message = (
            f"Provider {snapshot.provider_type} estimated remaining funded credit is "
            f"${snapshot.remaining_usd_internal:.2f}. Review or top up the provider "
            "before live project capacity is affected."
        )
    return await communications.notify_audience(
        session,
        organization_id="platform",
        audience="platform_owner",
        event_key=f"project_ai.provider_credit.{snapshot.state}",
        category="billing",
        title=title,
        message=message,
        severity=severity,
        channels=owner_alert_channels(),
        source_type="ai_provider",
        source_id=snapshot.provider_id,
        correlation_id=snapshot.provider_id,
        dedupe_prefix=(
            f"project-ai-credit:{snapshot.provider_id}:v{snapshot.policy_version}:{snapshot.state}"
        ),
        payload=snapshot.public(),
        respect_preferences=False,
    )


async def _notify_predictive_monitoring_gap(
    session: AsyncSession,
    snapshot: ProviderCreditSnapshot,
) -> list:
    if not snapshot.enabled or snapshot.funding_mode != "owner_attested":
        return []
    return await communications.notify_audience(
        session,
        organization_id="platform",
        audience="platform_owner",
        event_key="project_ai.provider_credit.predictive_monitoring_required",
        category="billing",
        title="AI provider predictive credit alert needs a numeric baseline",
        message=(
            f"Provider {snapshot.provider_type} is confirmed funded, but its exact funded "
            "amount is not recorded in AIONEX. Record the numeric funded amount plus low and "
            "critical thresholds in Owner > Project AI to receive warnings before the "
            "balance is estimated to run out. Billing/quota failures remain monitored now."
        ),
        severity="warning",
        channels=owner_alert_channels(),
        source_type="ai_provider",
        source_id=snapshot.provider_id,
        correlation_id=snapshot.provider_id,
        dedupe_prefix=(
            f"project-ai-credit:{snapshot.provider_id}:v{snapshot.policy_version}:predictive-required"
        ),
        payload=snapshot.public(),
        respect_preferences=False,
    )


async def run_provider_credit_alerts(session: AsyncSession) -> list:
    records = list(
        (
            await session.scalars(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == PROVIDER_FINANCE_DOMAIN,
                    OwnerControlRecord.status == "active",
                    OwnerControlRecord.enabled.is_(True),
                )
            )
        ).all()
    )
    notifications: list = []
    for record in records:
        try:
            snapshot = await provider_credit_snapshot(
                session, provider_id=record.resource_id
            )
        except ProviderCreditPolicyError:
            continue
        notifications.extend(await _notify_credit_state(session, snapshot))
        notifications.extend(await _notify_predictive_monitoring_gap(session, snapshot))
    return notifications


async def notify_provider_billing_failure(
    session: AsyncSession,
    *,
    provider_id: str,
    failure_code: str,
    critical: bool,
) -> list:
    provider = await session.get(AIProvider, provider_id)
    if provider is None:
        return []
    code = str(failure_code or "provider_failure").strip().lower()[:120]
    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    return await communications.notify_audience(
        session,
        organization_id=provider.organization_id,
        audience="platform_owner",
        event_key=(
            "project_ai.provider_billing.action_required"
            if critical
            else "project_ai.provider_quota.limited"
        ),
        category="billing" if critical else "quota",
        title=(
            "AI provider billing needs Owner attention"
            if critical
            else "AI provider quota is limiting capacity"
        ),
        message=(
            f"Provider {provider.type} returned a {'billing' if critical else 'quota'} failure "
            f"({code}). Review the provider account before launch capacity is affected."
        ),
        severity="critical" if critical else "warning",
        channels=owner_alert_channels(),
        source_type="ai_provider",
        source_id=provider.id,
        correlation_id=provider.id,
        dedupe_prefix=f"provider-failure:{provider.id}:{code}:{hour}",
        payload={"provider_id": provider.id, "provider_type": provider.type, "failure_code": code},
        respect_preferences=False,
    )
