from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GrowthSocialProviderCapability

SUPPORTED_PROVIDERS = (
    "meta",
    "instagram",
    "x",
    "tiktok",
    "linkedin",
    "youtube",
    "telegram",
    "pinterest",
    "snapchat",
    "reddit",
    "discord",
)

SAFE_VALIDATION_MODES = {"contract", "read_only", "sandbox"}
LIVE_MUTATION_MODES = {"live_write", "live_spend", "live_publish", "live_send"}


@dataclass(frozen=True)
class ProviderConnectorDescriptor:
    provider: str
    oauth_required: bool
    credential_reference_required: bool
    supported_validation_modes: tuple[str, ...]
    live_mutation_allowed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "oauth_required": self.oauth_required,
            "credential_reference_required": self.credential_reference_required,
            "supported_validation_modes": list(self.supported_validation_modes),
            "live_mutation_allowed": self.live_mutation_allowed,
        }


CONNECTORS: dict[str, ProviderConnectorDescriptor] = {
    provider: ProviderConnectorDescriptor(
        provider=provider,
        oauth_required=provider not in {"telegram", "discord"},
        credential_reference_required=True,
        supported_validation_modes=("contract", "read_only", "sandbox"),
        live_mutation_allowed=False,
    )
    for provider in SUPPORTED_PROVIDERS
}


def connector_catalog() -> list[dict[str, Any]]:
    return [CONNECTORS[name].as_dict() for name in sorted(CONNECTORS)]


def validate_credential_ref(value: str | None) -> tuple[bool, str]:
    if not value:
        return False, "credential-reference-missing"
    lowered = value.lower()
    if any(
        marker in lowered
        for marker in ("token=", "secret=", "password=", "bearer ", "api_key=")
    ):
        return False, "raw-credential-material-forbidden"
    if len(value) > 320:
        return False, "credential-reference-too-long"
    if "://" in value and not value.startswith("secretref://"):
        return False, "credential-reference-scheme-forbidden"
    return True, "credential-reference-valid"


def validation_preview(
    provider: str,
    capability: str,
    mode: str,
    credential_ref: str | None,
    platform_approval: bool,
) -> dict[str, Any]:
    descriptor = CONNECTORS.get(provider)
    if descriptor is None:
        return {
            "allowed": False,
            "reason": "unsupported-provider",
            "verification_state": "unverified",
            "provider_call_allowed": False,
            "mutation_allowed": False,
            "spend_allowed": False,
        }

    if mode in LIVE_MUTATION_MODES:
        return {
            "allowed": False,
            "reason": "live-mutation-blocked-in-gs09",
            "verification_state": "unverified",
            "provider_call_allowed": False,
            "mutation_allowed": False,
            "spend_allowed": False,
        }

    if mode not in SAFE_VALIDATION_MODES:
        return {
            "allowed": False,
            "reason": "unsupported-validation-mode",
            "verification_state": "unverified",
            "provider_call_allowed": False,
            "mutation_allowed": False,
            "spend_allowed": False,
        }

    credential_ok, credential_reason = validate_credential_ref(credential_ref)
    if mode == "contract":
        return {
            "allowed": True,
            "reason": "contract-validation-only",
            "verification_state": "unverified",
            "provider_call_allowed": False,
            "mutation_allowed": False,
            "spend_allowed": False,
        }

    if not credential_ok:
        return {
            "allowed": False,
            "reason": credential_reason,
            "verification_state": "unverified",
            "provider_call_allowed": False,
            "mutation_allowed": False,
            "spend_allowed": False,
        }

    if not platform_approval:
        return {
            "allowed": False,
            "reason": "platform-approval-required",
            "verification_state": "unverified",
            "provider_call_allowed": False,
            "mutation_allowed": False,
            "spend_allowed": False,
        }

    state = "read_only_ready" if mode == "read_only" else "sandbox_ready"
    return {
        "allowed": True,
        "reason": "external-validation-ready",
        "verification_state": state,
        "provider_call_allowed": True,
        "mutation_allowed": False,
        "spend_allowed": False,
    }


async def record_contract_evidence(
    session: AsyncSession,
    provider: str,
    capability: str,
    actor_id: str,
) -> GrowthSocialProviderCapability:
    row = await session.scalar(
        select(GrowthSocialProviderCapability).where(
            GrowthSocialProviderCapability.provider == provider,
            GrowthSocialProviderCapability.capability == capability,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = GrowthSocialProviderCapability(
            provider=provider,
            capability=capability,
            verification_state="unverified",
            mutation_class="read",
            evidence={},
        )
        session.add(row)

    evidence = dict(row.evidence or {})
    evidence.update(
        {
            "gs09_contract_checked_at": now.isoformat(),
            "checked_by": actor_id,
            "provider_call_allowed": False,
            "mutation_allowed": False,
            "spend_allowed": False,
        }
    )
    row.evidence = evidence
    row.simulated_at = now
    row.verification_state = "unverified"
    row.verified_at = None
    row.version += 1
    await session.flush()
    return row
