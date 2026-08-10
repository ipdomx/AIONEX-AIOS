"""Admission, target authorization and policy primitives for AIONEX Security Lab."""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
import socket
from datetime import UTC, datetime
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
}
DEFAULT_POLICY: dict[str, Any] = {
    "enabled": True,
    "managed_domain_suffixes": ["vip-e.net"],
    "max_concurrent_scans_per_user": 2,
    "max_scan_runtime_seconds": 1800,
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
}


def now() -> datetime:
    return datetime.now(UTC)


def normalize_origin(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Security target must be an http(s) origin")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Security target must be an origin without credentials, path, query, or fragment")
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
        raise ValueError("Security targets must resolve only to public routable addresses")


def assert_public_target(hostname: str) -> list[str]:
    """Fail closed against loopback/private/link-local/metadata SSRF targets."""
    try:
        _assert_global_ip(hostname)
        return [hostname]
    except ValueError as literal_error:
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise literal_error
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Security target hostname did not resolve") from exc
    addresses = sorted({item[4][0] for item in infos})
    if not addresses:
        raise ValueError("Security target hostname did not resolve")
    for address in addresses:
        _assert_global_ip(address)
    return addresses


async def get_policy(session: AsyncSession, *, for_update: bool = False) -> dict[str, Any]:
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
    policy["enabled"] = bool(record.enabled and policy.get("enabled", True))
    return policy


async def update_policy(session: AsyncSession, updates: dict[str, Any]) -> dict[str, Any]:
    current = await get_policy(session, for_update=True)
    stmt = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == POLICY_DOMAIN,
        OwnerControlRecord.resource_id == POLICY_RESOURCE,
    ).with_for_update()
    record = await session.scalar(stmt)
    assert record is not None
    merged = {**current, **updates}
    if "release_gate" in updates:
        merged["release_gate"] = {**current["release_gate"], **dict(updates["release_gate"])}
    suffixes = [str(value).lower().strip().lstrip(".") for value in merged.get("managed_domain_suffixes", []) if str(value).strip()]
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
            or_(SecurityAccessGrant.expires_at.is_(None), SecurityAccessGrant.expires_at > now()),
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
        select(SecurityAccessGrant).where(
            SecurityAccessGrant.organization_id == actor.organization_id,
            SecurityAccessGrant.user_id == user_id,
        ).with_for_update()
    )
    allowed_profiles = sorted({value for value in (profiles or []) if profile_allowed(level, value)})
    if not allowed_profiles:
        max_rank = PROFILE_RANK[LEVEL_MAX_PROFILE[level]]
        allowed_profiles = [name for name, rank in PROFILE_RANK.items() if rank <= max_rank]
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


async def revoke_access(session: AsyncSession, actor: UserRecord, user_id: str) -> SecurityAccessGrant:
    if actor.role != "Super Owner":
        raise PermissionError("Only the Super Owner can revoke Security Lab access")
    grant = await session.scalar(
        select(SecurityAccessGrant).where(
            SecurityAccessGrant.organization_id == actor.organization_id,
            SecurityAccessGrant.user_id == user_id,
        ).with_for_update()
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


async def _project_access(session: AsyncSession, actor: UserRecord, project_id: str) -> Project:
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
    normalized, hostname = normalize_origin(origin)
    policy = await get_policy(session)
    if not host_matches_suffix(hostname, list(policy["managed_domain_suffixes"])):
        raise PermissionError("Managed target hostname is outside Owner-approved deployment domains")
    addresses = assert_public_target(hostname)
    project = await _project_access(session, actor, project_id)
    target = await session.scalar(
        select(SecurityTarget).where(
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.origin == normalized,
        ).with_for_update()
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
        "environment": environment.strip().lower() or "production",
        "verified_addresses": addresses,
    }
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
        select(SecurityTarget).where(
            SecurityTarget.organization_id == actor.organization_id,
            SecurityTarget.origin == normalized,
        ).with_for_update()
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
        target.authorization_status = "pending"
        target.challenge_hash = digest
        target.active_scan_allowed = False
        target.verified_at = None
        target.revoked_at = None
        target.target_metadata = {**dict(target.target_metadata or {}), "verified_addresses": addresses}
    await session.flush()
    return target, raw_challenge


async def verify_external_target(
    session: AsyncSession,
    actor: UserRecord,
    target: SecurityTarget,
    *,
    challenge: str,
) -> SecurityTarget:
    if target.organization_id != actor.organization_id or target.kind != "external_authorized":
        raise PermissionError("External target is not available")
    if target.challenge_hash != hashlib.sha256(challenge.encode()).hexdigest():
        raise ValueError("Verification challenge does not match")
    current_addresses = assert_public_target(target.hostname)
    url = target.origin.rstrip("/") + "/.well-known/aionex-security-verification.txt"
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        response = await client.get(url, headers={"User-Agent": "AIONEX-Security-Verification/1.0"})
    if response.status_code != 200 or response.text.strip() != challenge:
        raise ValueError("External target verification file was not confirmed")
    policy = await get_policy(session)
    target.authorization_status = "verified"
    target.verified_by_id = actor.id
    target.verified_at = now()
    target.active_scan_allowed = bool(policy["active_on_verified_targets"])
    target.target_metadata = {**dict(target.target_metadata or {}), "verified_addresses": current_addresses}
    target.challenge_hash = None
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="security.target.verified",
            resource_type="security_target",
            resource_id=target.id,
            details={"hostname": target.hostname, "method": target.verification_method},
        )
    )
    return target


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
        "metadata": target.target_metadata,
        "verified_at": target.verified_at.isoformat() if target.verified_at else None,
    }
