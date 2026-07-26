from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import secrets


@dataclass
class DashboardAccessToken:
    token: str
    user_id: str
    organization_id: str | None
    capabilities: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return not self.revoked and current < self.expires_at


class DashboardTokenService:
    def __init__(self) -> None:
        self._tokens: dict[str, DashboardAccessToken] = {}

    def issue(
        self,
        user_id: str,
        capabilities: set[str],
        organization_id: str | None = None,
        ttl_minutes: int = 30,
    ) -> DashboardAccessToken:
        if not user_id.strip():
            raise ValueError("user_id is required")
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be positive")
        now = datetime.now(timezone.utc)
        token = DashboardAccessToken(
            token=secrets.token_urlsafe(32),
            user_id=user_id,
            organization_id=organization_id,
            capabilities=frozenset(capabilities),
            issued_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
        self._tokens[token.token] = token
        return token

    def validate(self, token_value: str, required_capability: str | None = None) -> DashboardAccessToken:
        try:
            token = self._tokens[token_value]
        except KeyError as exc:
            raise PermissionError("unknown dashboard token") from exc
        if not token.is_active():
            raise PermissionError("dashboard token is inactive")
        if required_capability and required_capability not in token.capabilities:
            raise PermissionError(f"missing capability: {required_capability}")
        return token

    def revoke(self, token_value: str) -> None:
        self.validate(token_value).revoked = True
