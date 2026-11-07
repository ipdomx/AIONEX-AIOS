"""Admission, target authorization and policy primitives for AIONEX Security Lab."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    OwnerControlRecord,
    Project,
    ProjectMembership,
    SecurityAccessGrant,
    SecurityTarget,
    User,
    uuid_str,
)

POLICY_DOMAIN = "security-lab-policy"
POLICY_RESOURCE = "default"
ACCESS_LEVELS = ("standard", "advanced", "elite", "autonomous")
PROFILE_RANK = {"passive": 0, "standard": 1, "advanced": 2, "elite": 3}
LEVEL_MAX_PROFILE = {
    "standard": "standard",
    "advanced": "advanced",
    "elite": "elite",
    "autonomous": "elite",
    "owner": "elite",
    # Automatic access from an active top-plan subscription. Advanced/Elite
    # remain Owner-granted because they require an isolated security clone.
    "subscriber": "standard",
}
VERIFICATION_METHODS = ("http_file", "dns_txt")
HTTP_VERIFICATION_PATH = "/.well-known/aionex-security-verification.txt"
# The proof file holds one challenge line; a larger body is not a valid proof.
VERIFICATION_MAX_RESPONSE_BYTES = 4096
# Tests inject an ``httpx.MockTransport`` here; production uses the default.
_VERIFICATION_TRANSPORT: httpx.AsyncBaseTransport | None = None
SUBSCRIPTION_ACCESS_DEFAULTS: dict[str, Any] = {
    # Subscribers on an entitled plan get scanning automatically. A plan is
    # entitled when its code is listed in ``plan_codes``; when that list is
    # empty, when it carries the ``entitlement`` flag in the billing catalogue;
    # and when no active plan carries the flag, the top-ranked active plan
    # (highest monthly price) is entitled.
    "enabled": True,
    "entitlement": "security.web_scanning",
    "plan_codes": [],
    "max_verified_targets": 3,
    "max_scans_per_month": 20,
    "max_concurrent_scans": 1,
    "reverify_after_days": 30,
    "dns_timeout_seconds": 5,
}
DEFAULT_POLICY: dict[str, Any] = {
    "enabled": True,
    "managed_domain_suffixes": ["vip-e.net"],
    "max_concurrent_scans_per_user": 2,
    "max_scan_runtime_seconds": 3600,
    "active_on_verified_targets": True,
    "deep_validation_requires_clone": True,
    "learning_enabled": True,
    "auto_rule_candidates": True,
    "auto_remediation_enabled": False,
    "release_gate": {
        "block_confirmed_critical": True,
        "block_confirmed_high": True,
        "max_confirmed_medium": 0,
        "require_tls": True,
        "require_security_headers": True,
        "require_backup_restore_evidence": True,
    },
    "subscription_access": dict(SUBSCRIPTION_ACCESS_DEFAULTS),
}


def now() -> datetime:
    return datetime.now(UTC)


def normalize_origin(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Security target must be an http(s) origin")
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Security target must be an origin without credentials, path, query, or fragment"
        )
    hostname = parsed.hostname.lower().rstrip(".")
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    suffix = "" if port == default_port else f":{port}"
    return f"{parsed.scheme}://{hostname}{suffix}", hostname


def host_matches_suffix(hostname: str, suffixes: list[str]) -> bool:
    host = hostname.lower().rstrip(".")
    for raw in suffixes:
        suffix = str(raw).lower().strip().lstrip(".").rstrip(".")
        if suffix and (host == suffix or host.endswith("." + suffix)):
            return True
    return False


def _assert_global_ip(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if not ip.is_global:
        raise ValueError(
            "Security targets must resolve only to public routable addresses"
        )


def assert_public_target(hostname: str) -> list[str]:
    """Fail closed against loopback/private/link-local/metadata SSRF targets."""
    try:
        _assert_global_ip(hostname)
        return [hostname]
    except ValueError as literal_error:
        try:
            literal_address = ipaddress.ip_address(hostname)
        except ValueError:
            literal_address = None
        if literal_address is not None:
            raise literal_error
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Security target hostname did not resolve") from exc
    address_set: set[str] = set()
    for item in infos:
        raw_address = item[4][0]
        if not isinstance(raw_address, str):
            raise ValueError("Security target hostname resolved to an unsupported address")
        address_set.add(raw_address)
    addresses = sorted(address_set)
    if not addresses:
        raise ValueError("Security target hostname did not resolve")
    for address in addresses:
        _assert_global_ip(address)
    return addresses


def assert_target_dns_stable(target: SecurityTarget) -> list[str]:
    current = assert_public_target(target.hostname)
    previous = sorted(
        str(value)
        for value in (target.target_metadata or {}).get("verified_addresses", [])
        if str(value)
    )
    if previous and sorted(current) != previous:
        raise ValueError(
            "Security target DNS changed after authorization; re-verify the target before scanning"
        )
    return current


async def get_policy(
    session: AsyncSession, *, for_update: bool = False
) -> dict[str, Any]:
    stmt = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == POLICY_DOMAIN,
        OwnerControlRecord.resource_id == POLICY_RESOURCE,
    )
    if for_update:
        stmt = stmt.with_for_update()
    record = await session.scalar(stmt)
    if record is None:
        record = OwnerControlRecord(
            id=uuid_str(),
            domain=POLICY_DOMAIN,
            resource_id=POLICY_RESOURCE,
            status="active",
            enabled=True,
            payload=DEFAULT_POLICY,
            version=1,
        )
        session.add(record)
        await session.flush()
    policy = {**DEFAULT_POLICY, **dict(record.payload or {})}
    policy["release_gate"] = {
        **DEFAULT_POLICY["release_gate"],
        **dict(policy.get("release_gate") or {}),
    }
    policy["subscription_access"] = normalize_subscription_access(
        dict(policy.get("subscription_access") or {})
    )
    policy["enabled"] = bool(record.enabled and policy.get("enabled", True))
    return policy


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def normalize_subscription_access(raw: dict[str, Any]) -> dict[str, Any]:
    merged = {**SUBSCRIPTION_ACCESS_DEFAULTS, **raw}
    codes = sorted(
        {
            str(value).strip().lower().replace("_", "-").replace(" ", "-")
            for value in list(merged.get("plan_codes") or [])
            if str(value).strip()
        }
    )
    if len(codes) > 20:
        raise ValueError("Too many Security Lab subscription plan codes")
    entitlement = str(merged.get("entitlement") or "").strip()
    defaults = SUBSCRIPTION_ACCESS_DEFAULTS
    return {
        "enabled": bool(merged.get("enabled", True)),
        "entitlement": entitlement[:120] or defaults["entitlement"],
        "plan_codes": codes,
        "max_verified_targets": _bounded_int(
            merged.get("max_verified_targets"), defaults["max_verified_targets"], 0, 1000
        ),
        "max_scans_per_month": _bounded_int(
            merged.get("max_scans_per_month"), defaults["max_scans_per_month"], 0, 100000
        ),
        "max_concurrent_scans": _bounded_int(
            merged.get("max_concurrent_scans"), defaults["max_concurrent_scans"], 1, 10
        ),
        "reverify_after_days": _bounded_int(
            merged.get("reverify_after_days"), defaults["reverify_after_days"], 1, 365
        ),
        "dns_timeout_seconds": _bounded_int(
            merged.get("dns_timeout_seconds"), defaults["dns_timeout_seconds"], 1, 15
        ),
    }


async def update_policy(
    session: AsyncSession, updates: dict[str, Any]
) -> dict[str, Any]:
    current = await get_policy(session, for_update=True)
    stmt = (
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == POLICY_DOMAIN,
            OwnerControlRecord.resource_id == POLICY_RESOURCE,
        )
        .with_for_update()
    )
    record = await session.scalar(stmt)
    assert record is not None
    merged = {**current, **updates}
    if "release_gate" in updates:
        merged["release_gate"] = {
            **current["release_gate"],
            **dict(updates["release_gate"]),
        }
    if "subscription_access" in updates:
        merged["subscription_access"] = normalize_subscription_access(
            {
                **current["subscription_access"],
                **dict(updates["subscription_access"]),
            }
        )
    suffixes = [
        str(value).lower().strip().lstrip(".")
        for value in merged.get("managed_domain_suffixes", [])
        if str(value).strip()
    ]
    if len(suffixes) > 100:
        raise ValueError("Too many managed domain suffixes")
    merged["managed_domain_suffixes"] = sorted(set(suffixes))
    record.payload = merged
    record.enabled = bool(merged["enabled"])
    record.version += 1
    return merged


async def access_level(session: AsyncSession, actor: UserRecord) -> str | None:
    if actor.role == "Super Owner":
        return "owner"
    grant = await session.scalar(
        select(SecurityAccessGrant).where(
            SecurityAccessGrant.organization_id == actor.organization_id,
            SecurityAccessGrant.user_id == actor.id,
            SecurityAccessGrant.status == "active",
            or_(
                SecurityAccessGrant.expires_at.is_(None),
                SecurityAccessGrant.expires_at > now(),
            ),
        )
    )
    return grant.level if grant is not None else None


def profile_allowed(level: str | None, profile: str) -> bool:
    if level not in LEVEL_MAX_PROFILE or profile not in PROFILE_RANK:
        return False
    return PROFILE_RANK[profile] <= PROFILE_RANK[LEVEL_MAX_PROFILE[level]]


async def grant_access(
    session: AsyncSession,
    actor: UserRecord,
    *,
    user_id: str,
    level: str,
    profiles: list[str] | None = None,
    expires_at: datetime | None = None,
    notes: str | None = None,
) -> SecurityAccessGrant:
    if actor.role != "Super Owner":
        raise PermissionError("Only the Super Owner can grant Security Lab access")
    if level not in ACCESS_LEVELS:
        raise ValueError("Unsupported Security Lab access level")
    user = await session.scalar(
        select(User).where(
            User.id == user_id,
            User.organization_id == actor.organization_id,
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        raise LookupError("Security Lab user not found")
    grant = await session.scalar(
        select(SecurityAccessGrant)
        .where(
            SecurityAccessGrant.organization_id == actor.organization_id,
            SecurityAccessGrant.user_id == user_id,
        )
        .with_for_update()
    )
    allowed_profiles = sorted(
        {value for value in (profiles or []) if profile_allowed(level, value)}
    )
    if not allowed_profiles:
        max_rank = PROFILE_RANK[LEVEL_MAX_PROFILE[level]]
        allowed_profiles = [
            name for name, rank in PROFILE_RANK.items() if rank <= max_rank
        ]
    if grant is None:
        grant = SecurityAccessGrant(
            id=uuid_str(),
            organization_id=actor.organization_id,
            user_id=user_id,
            granted_by_id=actor.id,
            level=level,
            status="active",
            profiles=allowed_profiles,
        )
        session.add(grant)
    else:
        grant.granted_by_id = actor.id
        grant.level = level
        grant.status = "active"
        grant.profiles = allowed_profiles
        grant.revoked_at = None
    grant.expires_at = expires_at
    grant.notes = (notes or "").strip() or None
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.access.granted",
            resource_type="security_access_grant",
            resource_id=grant.id,
            details={"user_id": user_id, "level": level, "profiles": allowed_profiles},
        )
    )
    await session.flush()
    return grant


async def revoke_access(
    session: AsyncSession, actor: UserRecord, user_id: str
) -> SecurityAccessGrant:
    if actor.role != "Super Owner":
        raise PermissionError("Only the Super Owner can revoke Security Lab access")
    grant = await session.scalar(
        select(SecurityAccessGrant)
        .where(
            SecurityAccessGrant.organization_id == actor.organization_id,
            SecurityAccessGrant.user_id == user_id,
        )
        .with_for_update()
    )
    if grant is None:
        raise LookupError("Security Lab grant not found")
    grant.status = "revoked"
    grant.revoked_at = now()
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.access.revoked",
            resource_type="security_access_grant",
            resource_id=grant.id,
            details={"user_id": user_id},
        )
    )
    return grant


async def _project_access(
    session: AsyncSession, actor: UserRecord, project_id: str
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.organization_id == actor.organization_id,
            Project.status != "deleted",
        )
    )
    if project is None:
        raise LookupError("Security project not found")
    if actor.role == "Super Owner" or project.owner_id == actor.id:
        return project
    membership = await session.scalar(
        select(ProjectMembership.id).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.organization_id == actor.organization_id,
            ProjectMembership.user_id == actor.id,
            ProjectMembership.status == "active",
        )
    )
    if membership is None:
        raise PermissionError("Project membership is required for Security Lab")
    return project


async def register_managed_target(
    session: AsyncSession,
    actor: UserRecord,
    *,
    project_id: str,
    origin: str,
    environment: str = "production",
) -> SecurityTarget:
    if actor.role != "Super Owner":
        raise PermissionError(
            "Managed AIONEX deployment targets are registered only by the Super Owner or trusted deployment automation"
        )
    normalized, hostname = normalize_origin(origin)
    environment = environment.strip().lower() or "production"
    if environment not in {"production", "staging"}:
        raise ValueError(
            "Managed project targets may be production or staging; security clones are provisioned separately by the Super Owner"
        )
    policy = await get_policy(session)
    if not host_matches_suffix(hostname, list(policy["managed_domain_suffixes"])):
        raise PermissionError(
            "Managed target hostname is outside Owner-approved deployment domains"
        )
    addresses = assert_public_target(hostname)
    project = await _project_access(session, actor, project_id)
    target = await session.scalar(
        select(SecurityTarget)
        .where(
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.origin == normalized,
        )
        .with_for_update()
    )
    if target is not None and target.kind != "managed_project":
        raise ValueError(
            "Target origin is already registered under a different authorization type"
        )
    if target is None:
        target = SecurityTarget(
            id=uuid_str(),
            organization_id=actor.organization_id,
            project_id=project.id,
            created_by_id=actor.id,
            verified_by_id=actor.id,
            kind="managed_project",
            origin=normalized,
            hostname=hostname,
            authorization_status="verified",
            verification_method="managed_project",
            active_scan_allowed=bool(policy["active_on_verified_targets"]),
            status="active",
            target_metadata={},
            verified_at=now(),
        )
        session.add(target)
    target.project_id = project.id
    target.authorization_status = "verified"
    target.verified_by_id = actor.id
    target.verified_at = now()
    target.revoked_at = None
    target.status = "active"
    target.target_metadata = {
        **dict(target.target_metadata or {}),
        "environment": environment,
        "verified_addresses": addresses,
    }
    await session.flush()
    return target


async def register_security_clone_target(
    session: AsyncSession,
    actor: UserRecord,
    *,
    source_target_id: str,
    origin: str,
) -> SecurityTarget:
    if actor.role != "Super Owner":
        raise PermissionError(
            "Only the Super Owner can register an isolated Security Lab clone target"
        )
    source = await session.scalar(
        select(SecurityTarget).where(
            SecurityTarget.id == source_target_id,
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.kind == "managed_project",
            SecurityTarget.authorization_status == "verified",
            SecurityTarget.status == "active",
        )
    )
    if source is None or source.project_id is None:
        raise LookupError("Managed source target not found")
    normalized, hostname = normalize_origin(origin)
    if normalized == source.origin:
        raise ValueError(
            "Security clone origin must be different from the managed source target"
        )
    policy = await get_policy(session)
    if not host_matches_suffix(hostname, list(policy["managed_domain_suffixes"])):
        raise PermissionError(
            "Security clone hostname is outside Owner-approved deployment domains"
        )
    addresses = assert_public_target(hostname)
    target = await session.scalar(
        select(SecurityTarget)
        .where(
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.origin == normalized,
        )
        .with_for_update()
    )
    if target is not None and target.kind != "security_clone":
        raise ValueError(
            "Security clone origin is already registered under a different authorization type"
        )
    if target is None:
        target = SecurityTarget(
            id=uuid_str(),
            organization_id=actor.organization_id,
            project_id=source.project_id,
            created_by_id=actor.id,
            verified_by_id=actor.id,
            kind="security_clone",
            origin=normalized,
            hostname=hostname,
            authorization_status="verified",
            verification_method="owner_managed_clone",
            active_scan_allowed=True,
            status="active",
            target_metadata={},
            verified_at=now(),
        )
        session.add(target)
    target.project_id = source.project_id
    target.kind = "security_clone"
    target.authorization_status = "verified"
    target.verified_by_id = actor.id
    target.verified_at = now()
    target.active_scan_allowed = True
    target.status = "active"
    target.revoked_at = None
    target.target_metadata = {
        **dict(target.target_metadata or {}),
        "environment": "security_clone",
        "source_target_id": source.id,
        "verified_addresses": addresses,
    }
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.clone_target.registered",
            resource_type="security_target",
            resource_id=target.id,
            details={
                "source_target_id": source.id,
                "project_id": source.project_id,
                "hostname": hostname,
            },
        )
    )
    await session.flush()
    return target


async def register_external_target(
    session: AsyncSession,
    actor: UserRecord,
    *,
    origin: str,
) -> tuple[SecurityTarget, str]:
    normalized, hostname = normalize_origin(origin)
    addresses = assert_public_target(hostname)
    raw_challenge = "aionex-verify-" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw_challenge.encode()).hexdigest()
    target = await session.scalar(
        select(SecurityTarget)
        .where(
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.origin == normalized,
        )
        .with_for_update()
    )
    if target is not None and target.kind != "external_authorized":
        raise ValueError(
            "Target origin is already registered as an AIONEX-managed target"
        )
    if target is None:
        target = SecurityTarget(
            id=uuid_str(),
            organization_id=actor.organization_id,
            created_by_id=actor.id,
            kind="external_authorized",
            origin=normalized,
            hostname=hostname,
            authorization_status="pending",
            verification_method="http_file",
            challenge_hash=digest,
            active_scan_allowed=False,
            status="active",
            target_metadata={"verified_addresses": addresses},
        )
        session.add(target)
    else:
        if target.status != "active":
            # An archived origin re-enters the inventory under the actor that
            # re-registers it and must prove ownership again.
            target.created_by_id = actor.id
            target.status = "active"
        target.authorization_status = "pending"
        target.challenge_hash = digest
        target.active_scan_allowed = False
        target.verified_at = None
        target.revoked_at = None
        metadata = dict(target.target_metadata or {})
        metadata.pop("verification", None)
        target.target_metadata = {**metadata, "verified_addresses": addresses}
    await session.flush()
    return target, raw_challenge


def verification_instructions(target: SecurityTarget, challenge: str) -> dict[str, Any]:
    from app.services import security_dns_verification as dns_verification

    return {
        # ``method``/``path``/``challenge`` keep the original response shape.
        "method": "http_file",
        "path": HTTP_VERIFICATION_PATH,
        "url": target.origin.rstrip("/") + HTTP_VERIFICATION_PATH,
        "challenge": challenge,
        "methods": {
            "http_file": {
                "method": "http_file",
                "available": True,
                "path": HTTP_VERIFICATION_PATH,
                "url": target.origin.rstrip("/") + HTTP_VERIFICATION_PATH,
                "content": challenge,
            },
            "dns_txt": dns_verification.instructions(target.hostname, challenge),
        },
    }


def _pinned_verification_request(
    target: SecurityTarget, address: str
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """URL, headers and extensions that connect to ``address`` for ``target``.

    The TCP connection goes to the already validated address; the Host header
    and the TLS SNI/certificate name stay the target hostname, so certificate
    verification is unchanged.
    """

    parsed = urlsplit(target.origin)
    scheme = parsed.scheme
    port = parsed.port or (443 if scheme == "https" else 80)
    literal = f"[{address}]" if ipaddress.ip_address(address).version == 6 else address
    url = f"{scheme}://{literal}:{port}{HTTP_VERIFICATION_PATH}"
    default_port = 443 if scheme == "https" else 80
    host_header = target.hostname if port == default_port else f"{target.hostname}:{port}"
    headers = {"Host": host_header, "User-Agent": "AIONEX-Security-Verification/1.0"}
    extensions: dict[str, Any] = {"sni_hostname": target.hostname} if scheme == "https" else {}
    return url, headers, extensions


async def _http_file_value(target: SecurityTarget) -> str | None:
    """Fetch the HTTP proof file without a DNS-rebinding window (FR-23).

    The hostname is resolved and checked here and the request is pinned to
    that exact address, so an answer that changes between the SSRF check and
    the connect cannot steer the request to an internal address. Redirects are
    not followed, at most ``VERIFICATION_MAX_RESPONSE_BYTES`` are read and a
    transport failure is reported as "not confirmed" instead of a 500.
    """

    addresses = assert_public_target(target.hostname)
    url, headers, extensions = _pinned_verification_request(target, addresses[0])
    body = bytearray()
    try:
        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=False, transport=_VERIFICATION_TRANSPORT
        ) as client:
            async with client.stream(
                "GET", url, headers=headers, extensions=extensions
            ) as response:
                if response.status_code != 200:
                    return None
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > VERIFICATION_MAX_RESPONSE_BYTES:
                        return None
    except httpx.HTTPError:
        return None
    return body.decode("utf-8", "replace").strip()


async def _confirm_ownership(
    target: SecurityTarget,
    *,
    method: str,
    matches: Any,
    dns_timeout: float,
) -> list[str]:
    """Fetch the published proof for ``method`` and test it with ``matches``.

    The target hostname must still resolve only to public addresses before any
    proof is fetched, so DNS TXT verification never weakens the SSRF guard.
    """

    from app.services import security_dns_verification as dns_verification

    if method not in VERIFICATION_METHODS:
        raise ValueError("Unsupported verification method")
    addresses = assert_public_target(target.hostname)
    if method == "dns_txt":
        tokens = await dns_verification.lookup_tokens(
            target.hostname, timeout=dns_timeout
        )
        if not any(matches(token) for token in tokens):
            raise dns_verification.DnsVerificationError(
                "DNS TXT verification record was not found for "
                + dns_verification.record_name(target.hostname)
            )
        return addresses
    value = await _http_file_value(target)
    if value is None or not matches(value):
        raise ValueError("External target verification file was not confirmed")
    return addresses


async def verify_external_target(
    session: AsyncSession,
    actor: UserRecord,
    target: SecurityTarget,
    *,
    challenge: str,
    method: str = "http_file",
) -> SecurityTarget:
    if (
        target.organization_id != actor.organization_id
        or target.kind != "external_authorized"
    ):
        raise PermissionError("External target is not available")
    digest = hashlib.sha256(challenge.encode()).hexdigest()
    if target.challenge_hash != digest:
        raise ValueError("Verification challenge does not match")
    policy = await get_policy(session)
    current_addresses = await _confirm_ownership(
        target,
        method=method,
        matches=lambda value: value == challenge,
        dns_timeout=float(policy["subscription_access"]["dns_timeout_seconds"]),
    )
    verified_at = now()
    target.authorization_status = "verified"
    target.verification_method = method
    target.verified_by_id = actor.id
    target.verified_at = verified_at
    target.active_scan_allowed = bool(policy["active_on_verified_targets"])
    target.target_metadata = {
        **dict(target.target_metadata or {}),
        "verified_addresses": current_addresses,
        # Only the digest is retained so ownership can be re-proven later
        # without storing the bearer challenge itself.
        "verification": {
            "method": method,
            "challenge_sha256": digest,
            "verified_at": verified_at.isoformat(),
        },
    }
    target.challenge_hash = None
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.target.verified",
            resource_type="security_target",
            resource_id=target.id,
            details={"hostname": target.hostname, "method": method},
        )
    )
    return target


def verification_is_stale(
    target: SecurityTarget, *, max_age_days: int, moment: datetime | None = None
) -> bool:
    if target.kind != "external_authorized":
        return False
    verified_at = target.verified_at
    if verified_at is None:
        return True
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    return (moment or now()) - verified_at > timedelta(days=max(1, int(max_age_days)))


async def reverify_external_target(
    session: AsyncSession, target: SecurityTarget
) -> SecurityTarget:
    """Re-prove ownership of a previously verified external target.

    Raises ``ValueError`` (or a DNS verification error) when the published proof
    is gone; callers must then refuse the scan without persisting anything.
    """

    metadata = dict(target.target_metadata or {})
    record = dict(metadata.get("verification") or {})
    digest = str(record.get("challenge_sha256") or "")
    method = str(record.get("method") or target.verification_method or "http_file")
    if len(digest) != 64 or method not in VERIFICATION_METHODS:
        raise ValueError(
            "Target verification has expired; register the target again to re-verify ownership"
        )
    policy = await get_policy(session)
    await _confirm_ownership(
        target,
        method=method,
        matches=lambda value: hashlib.sha256(value.encode()).hexdigest() == digest,
        dns_timeout=float(policy["subscription_access"]["dns_timeout_seconds"]),
    )
    verified_at = now()
    target.verified_at = verified_at
    target.target_metadata = {
        **metadata,
        "verification": {**record, "reverified_at": verified_at.isoformat()},
    }
    return target


def _public_metadata(raw: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(raw or {})
    if isinstance(metadata.get("verification"), dict):
        metadata["verification"] = {
            key: value
            for key, value in metadata["verification"].items()
            if key != "challenge_sha256"
        }
    return metadata


def target_snapshot(target: SecurityTarget) -> dict[str, Any]:
    return {
        "id": target.id,
        "project_id": target.project_id,
        "kind": target.kind,
        "origin": target.origin,
        "hostname": target.hostname,
        "authorization_status": target.authorization_status,
        "verification_method": target.verification_method,
        "active_scan_allowed": target.active_scan_allowed,
        "status": target.status,
        "metadata": _public_metadata(target.target_metadata),
        "verified_at": target.verified_at.isoformat() if target.verified_at else None,
    }
