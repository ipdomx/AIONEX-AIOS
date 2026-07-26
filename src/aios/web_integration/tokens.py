from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets

from .contracts import DashboardCapability


@dataclass(frozen=True)
class DashboardAccessToken:
    token_id: str
    subject_id: str
    dashboard_id: str
    capabilities: frozenset[DashboardCapability]
    issued_at: datetime
    expires_at: datetime
    signature: str
    metadata: dict[str, str] = field(default_factory=dict)

    def is_active(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) < self.expires_at


class DashboardTokenService:
    def __init__(self, secret: str | None = None) -> None:
        self._secret = (secret or secrets.token_urlsafe(48)).encode("utf-8")
        self._issued: dict[str, DashboardAccessToken] = {}

    def issue(
        self,
        subject_id: str,
        dashboard_id: str,
        capabilities: set[DashboardCapability] | frozenset[DashboardCapability],
        ttl_minutes: int = 30,
        metadata: dict[str, str] | None = None,
    ) -> DashboardAccessToken:
        if not subject_id.strip() or not dashboard_id.strip():
            raise ValueError("subject_id and dashboard_id are required")
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be positive")
        now = datetime.now(timezone.utc)
        token_id = secrets.token_urlsafe(18)
        capability_set = frozenset(capabilities)
        payload = {
            "token_id": token_id,
            "subject_id": subject_id,
            "dashboard_id": dashboard_id,
            "capabilities": sorted(item.value for item in capability_set),
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(),
        }
        signature = hmac.new(
            self._secret,
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        token = DashboardAccessToken(
            token_id=token_id,
            subject_id=subject_id,
            dashboard_id=dashboard_id,
            capabilities=capability_set,
            issued_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
            signature=signature,
            metadata=dict(metadata or {}),
        )
        self._issued[token_id] = token
        return token

    def get(self, token_id: str) -> DashboardAccessToken:
        try:
            return self._issued[token_id]
        except KeyError as exc:
            raise LookupError(f"dashboard token not found: {token_id}") from exc

    def validate(
        self,
        token_id: str,
        dashboard_id: str,
        required_capabilities: set[DashboardCapability] | frozenset[DashboardCapability],
    ) -> DashboardAccessToken:
        token = self.get(token_id)
        if token.dashboard_id != dashboard_id:
            raise PermissionError("dashboard token audience mismatch")
        if not token.is_active():
            raise PermissionError("dashboard token expired")
        missing = set(required_capabilities) - set(token.capabilities)
        if missing:
            raise PermissionError("dashboard token lacks required capabilities")
        return token
