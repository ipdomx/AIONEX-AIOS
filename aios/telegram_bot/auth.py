from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import TelegramIdentity


@dataclass(slots=True)
class LinkToken:
    token: str
    owner_id: str
    expires_at: datetime
    consumed: bool = False


class TelegramIdentityService:
    def __init__(self) -> None:
        self._tokens: dict[str, LinkToken] = {}
        self._identities: dict[str, TelegramIdentity] = {}

    def issue_link_token(self, owner_id: str, *, ttl_minutes: int = 10) -> LinkToken:
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be positive")
        token = secrets.token_urlsafe(24)
        link = LinkToken(
            token=token,
            owner_id=owner_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        )
        self._tokens[token] = link
        return link

    def link(
        self,
        *,
        token: str,
        telegram_user_id: str,
        username: str | None = None,
        display_name: str | None = None,
    ) -> TelegramIdentity:
        link = self._tokens.get(token)
        if link is None:
            raise PermissionError("invalid link token")
        if link.consumed:
            raise PermissionError("link token already consumed")
        if datetime.now(timezone.utc) >= link.expires_at:
            raise PermissionError("link token expired")
        if telegram_user_id in self._identities:
            raise ValueError("telegram user already linked")
        identity = TelegramIdentity(
            telegram_user_id=telegram_user_id,
            owner_id=link.owner_id,
            username=username,
            display_name=display_name,
        )
        self._identities[telegram_user_id] = identity
        link.consumed = True
        return identity

    def require_active(self, telegram_user_id: str) -> TelegramIdentity:
        identity = self._identities.get(telegram_user_id)
        if identity is None or not identity.active:
            raise PermissionError("telegram identity is not authorized")
        return identity

    def revoke(self, telegram_user_id: str, owner_id: str) -> TelegramIdentity:
        identity = self.require_active(telegram_user_id)
        if identity.owner_id != owner_id:
            raise PermissionError("identity does not belong to owner")
        identity.active = False
        return identity
