"""GS-03 managed social account registry and deterministic connector simulator.

No provider credential value is accepted or returned here. GS-03 never performs a
provider network call and cannot mark a capability as live verified.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    GrowthSocialAccount,
    GrowthSocialProviderCapability,
    Team,
)
from app.services import growth_access

PROVIDERS: tuple[str, ...] = (
    "facebook",
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

CAPABILITIES: dict[str, str] = {
    "account.read": "read",
    "content.publish": "write",
    "content.delete": "write",
    "analytics.read": "read",
    "inbox.read": "read",
    "inbox.reply": "write",
    "ads.manage": "write",
    "webhooks.receive": "read",
}

ACCOUNT_KINDS: tuple[str, ...] = (
    "ad_account",
    "profile",
    "page",
    "group",
    "business",
    "creator",
    "company",
    "channel",
    "bot",
    "server",
    "community",
    "board",
)

SAFE_CREDENTIAL_PREFIXES = ("file:", "vault:", "secret-ref:", "credential:")
SENSITIVE_KEYS = (
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "authorization",
    "cookie",
    "credential",
)
_CREDENTIAL_REF_RE = re.compile(r"^[A-Za-z0-9._:/@+-]{3,320}$")


class GrowthSocialAccountError(RuntimeError):
    """Fail-closed GS-03 registry error."""


async def _require(session: AsyncSession, actor: UserRecord) -> None:
    decision = await growth_access.effective_access(session, actor, "social.accounts")
    if not decision.allowed:
        raise GrowthSocialAccountError(f"access-denied:{decision.reason}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _assert_no_sensitive_keys(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).strip().lower()
            if any(marker in lowered for marker in SENSITIVE_KEYS):
                raise GrowthSocialAccountError(f"sensitive-field-rejected:{path}.{key}")
            _assert_no_sensitive_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_sensitive_keys(item, path=f"{path}[{index}]")


def validate_credential_ref(value: str | None) -> str | None:
    if value is None:
        return None
    ref = value.strip()
    if not ref:
        return None
    if not ref.startswith(SAFE_CREDENTIAL_PREFIXES):
        raise GrowthSocialAccountError(
            "credential-value-rejected-use-external-reference"
        )
    if not _CREDENTIAL_REF_RE.fullmatch(ref) or ".." in ref or "//" in ref:
        raise GrowthSocialAccountError("invalid-credential-reference")
    return ref


def _account_public(row: GrowthSocialAccount) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "account_kind": row.account_kind,
        "external_account_id": row.external_account_id,
        "display_name": row.display_name,
        "public_handle": row.public_handle,
        "workspace_id": row.workspace_id,
        "team_id": row.team_id,
        "status": row.status,
        "health_state": row.health_state,
        "health_reasons": list(row.health_reasons or []),
        "token_expires_at": row.token_expires_at,
        "last_health_at": row.last_health_at,
        "credential_configured": bool(row.credential_ref),
        "provider_metadata": dict(row.provider_metadata or {}),
        "settings": dict(row.settings or {}),
        "version": row.version,
    }


async def ensure_capability_matrix(session: AsyncSession) -> None:
    values = [
        {
            "provider": provider,
            "capability": capability,
            "verification_state": "unverified",
            "mutation_class": mutation_class,
            "evidence": {
                "source": "gs03-declarative-baseline",
                "live_verified": False,
            },
            "version": 1,
        }
        for provider in PROVIDERS
        for capability, mutation_class in CAPABILITIES.items()
    ]
    await session.execute(
        pg_insert(GrowthSocialProviderCapability)
        .values(values)
        .on_conflict_do_nothing(index_elements=["provider", "capability"])
    )
    await session.flush()


async def capability_matrix(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    await _require(session, actor)
    await ensure_capability_matrix(session)
    rows = (
        await session.scalars(
            select(GrowthSocialProviderCapability).order_by(
                GrowthSocialProviderCapability.provider,
                GrowthSocialProviderCapability.capability,
            )
        )
    ).all()
    return {
        "providers": PROVIDERS,
        "account_kinds": ACCOUNT_KINDS,
        "items": [
            {
                "provider": row.provider,
                "capability": row.capability,
                "verification_state": row.verification_state,
                "mutation_class": row.mutation_class,
                "live_verified": False,
                "simulated_at": row.simulated_at,
                "version": row.version,
            }
            for row in rows
        ],
        "live_provider_calls_allowed": False,
    }


async def register_account(
    session: AsyncSession,
    actor: UserRecord,
    payload: dict[str, Any],
) -> GrowthSocialAccount:
    await _require(session, actor)
    provider = str(payload.get("provider") or "").strip().lower()
    account_kind = str(payload.get("account_kind") or "").strip().lower()
    external_account_id = str(payload.get("external_account_id") or "").strip()
    display_name = str(payload.get("display_name") or "").strip()
    if provider not in PROVIDERS:
        raise GrowthSocialAccountError("unsupported-provider")
    if account_kind not in ACCOUNT_KINDS:
        raise GrowthSocialAccountError("unsupported-account-kind")
    if not external_account_id or not display_name:
        raise GrowthSocialAccountError("account-fields-required")
    metadata = dict(payload.get("provider_metadata") or {})
    settings = dict(payload.get("settings") or {})
    _assert_no_sensitive_keys(metadata, path="provider_metadata")
    _assert_no_sensitive_keys(settings, path="settings")
    credential_ref = validate_credential_ref(payload.get("credential_ref"))

    duplicate = await session.scalar(
        select(GrowthSocialAccount.id).where(
            GrowthSocialAccount.organization_id == actor.organization_id,
            GrowthSocialAccount.provider == provider,
            GrowthSocialAccount.external_account_id == external_account_id,
        )
    )
    if duplicate is not None:
        raise GrowthSocialAccountError("account-already-registered")

    row = GrowthSocialAccount(
        organization_id=actor.organization_id,
        created_by_id=actor.id,
        workspace_id=payload.get("workspace_id"),
        team_id=None,
        provider=provider,
        account_kind=account_kind,
        external_account_id=external_account_id[:255],
        display_name=display_name[:240],
        public_handle=(str(payload.get("public_handle") or "").strip() or None),
        credential_ref=credential_ref,
        status="active",
        health_state="unknown",
        health_reasons=["not-yet-simulated"],
        token_expires_at=payload.get("token_expires_at"),
        provider_metadata=metadata,
        settings=settings,
        version=1,
    )
    session.add(row)
    await session.flush()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="growth.social.account_registered",
            resource_type="growth_social_account",
            resource_id=row.id,
            details={
                "provider": provider,
                "account_kind": account_kind,
                "credential_configured": bool(credential_ref),
                "live_provider_call": False,
            },
        )
    )
    await session.flush()
    return row


async def list_accounts(
    session: AsyncSession, actor: UserRecord
) -> list[dict[str, Any]]:
    await _require(session, actor)
    rows = (
        await session.scalars(
            select(GrowthSocialAccount)
            .where(GrowthSocialAccount.organization_id == actor.organization_id)
            .order_by(
                GrowthSocialAccount.provider,
                GrowthSocialAccount.created_at.desc(),
            )
            .limit(500)
        )
    ).all()
    return [_account_public(row) for row in rows]


async def _account(
    session: AsyncSession, actor: UserRecord, account_id: str
) -> GrowthSocialAccount:
    await _require(session, actor)
    row = await session.scalar(
        select(GrowthSocialAccount).where(
            GrowthSocialAccount.id == account_id,
            GrowthSocialAccount.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise GrowthSocialAccountError("account-not-found")
    return row


def _audit(
    session: AsyncSession,
    actor: UserRecord,
    action: str,
    account: GrowthSocialAccount,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action=action,
            resource_type="growth_social_account",
            resource_id=account.id,
            details={
                "provider": account.provider,
                "live_provider_call": False,
                **dict(details or {}),
            },
        )
    )


async def pause_account(
    session: AsyncSession, actor: UserRecord, account_id: str
) -> dict[str, Any]:
    row = await _account(session, actor, account_id)
    if row.status == "revoked":
        raise GrowthSocialAccountError("revoked-account-is-terminal")
    row.status = "paused"
    row.paused_at = _utcnow()
    row.health_state = "paused"
    row.health_reasons = ["owner-or-user-paused"]
    row.version += 1
    _audit(session, actor, "growth.social.account_paused", row)
    await session.flush()
    return _account_public(row)


async def resume_account(
    session: AsyncSession, actor: UserRecord, account_id: str
) -> dict[str, Any]:
    row = await _account(session, actor, account_id)
    if row.status == "revoked":
        raise GrowthSocialAccountError("revoked-account-is-terminal")
    row.status = "active"
    row.paused_at = None
    row.health_state = "unknown"
    row.health_reasons = ["health-recheck-required"]
    row.version += 1
    _audit(session, actor, "growth.social.account_resumed", row)
    await session.flush()
    return _account_public(row)


async def disconnect_account(
    session: AsyncSession, actor: UserRecord, account_id: str
) -> dict[str, Any]:
    row = await _account(session, actor, account_id)
    row.status = "revoked"
    row.credential_ref = None
    row.health_state = "revoked"
    row.health_reasons = ["disconnected"]
    row.paused_at = None
    row.version += 1
    await session.flush()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="growth.social.account_disconnected",
            resource_type="growth_social_account",
            resource_id=row.id,
            details={"provider": row.provider, "credential_reference_cleared": True},
        )
    )
    await session.flush()
    return _account_public(row)


async def assign_team(
    session: AsyncSession,
    actor: UserRecord,
    account_id: str,
    team_id: str | None,
) -> dict[str, Any]:
    row = await _account(session, actor, account_id)
    if team_id is not None:
        team = await session.scalar(
            select(Team).where(
                Team.id == team_id,
                Team.organization_id == actor.organization_id,
                Team.status == "active",
            )
        )
        if team is None:
            raise GrowthSocialAccountError("team-not-found-or-inactive")
    row.team_id = team_id
    row.version += 1
    _audit(
        session,
        actor,
        "growth.social.account_team_assigned",
        row,
        {"team_id": team_id},
    )
    await session.flush()
    return _account_public(row)


def simulate_health_payload(
    *,
    status: str,
    credential_configured: bool,
    token_expires_at: datetime | None,
    now: datetime | None = None,
) -> tuple[str, list[str]]:
    current = now or _utcnow()
    if status == "revoked":
        return "revoked", ["account-revoked"]
    if status == "paused":
        return "paused", ["account-paused"]
    if status == "rate_limited":
        return "rate_limited", ["provider-rate-limited-metadata"]
    if status == "expired":
        return "expired", ["credential-expired"]
    if not credential_configured:
        return "unknown", ["credential-not-configured"]
    if token_expires_at is None:
        return "unknown", ["credential-expiry-unknown"]
    expiry = token_expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= current:
        return "expired", ["credential-expired"]
    if expiry <= current + timedelta(days=7):
        return "expiring", ["credential-expires-within-7-days"]
    return "healthy", ["metadata-health-simulation-passed"]


async def simulate_health(
    session: AsyncSession, actor: UserRecord, account_id: str
) -> dict[str, Any]:
    row = await _account(session, actor, account_id)
    state, reasons = simulate_health_payload(
        status=row.status,
        credential_configured=bool(row.credential_ref),
        token_expires_at=row.token_expires_at,
    )
    row.health_state = state
    row.health_reasons = reasons
    row.last_health_at = _utcnow()
    if state == "expired" and row.status == "active":
        row.status = "expired"
    row.version += 1
    _audit(
        session,
        actor,
        "growth.social.account_health_simulated",
        row,
        {"health_state": state, "health_reasons": reasons},
    )
    await session.flush()
    result = _account_public(row)
    result["simulated"] = True
    result["live_provider_call"] = False
    return result


async def simulate_capability(
    session: AsyncSession,
    actor: UserRecord,
    account_id: str,
    capability: str,
) -> dict[str, Any]:
    row = await _account(session, actor, account_id)
    if capability not in CAPABILITIES:
        raise GrowthSocialAccountError("unknown-capability")
    await ensure_capability_matrix(session)
    matrix = await session.scalar(
        select(GrowthSocialProviderCapability).where(
            GrowthSocialProviderCapability.provider == row.provider,
            GrowthSocialProviderCapability.capability == capability,
        )
    )
    if matrix is None:
        raise GrowthSocialAccountError("capability-matrix-missing")
    if matrix.verification_state == "verified":
        raise GrowthSocialAccountError("gs03-cannot-mutate-live-verification")
    matrix.verification_state = "simulated"
    matrix.simulated_at = _utcnow()
    matrix.verified_at = None
    matrix.evidence = {
        "source": "gs03-deterministic-connector-simulator",
        "live_verified": False,
        "account_kind": row.account_kind,
    }
    matrix.version += 1
    _audit(
        session,
        actor,
        "growth.social.capability_simulated",
        row,
        {"capability": capability, "verification_state": "simulated"},
    )
    await session.flush()
    return {
        "provider": row.provider,
        "account_id": row.id,
        "capability": capability,
        "verification_state": "simulated",
        "mutation_class": matrix.mutation_class,
        "simulated": True,
        "live_verified": False,
        "live_provider_call": False,
    }
