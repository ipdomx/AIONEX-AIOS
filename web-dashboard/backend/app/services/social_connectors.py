"""P3 social connector framework.

A connector is a plug-in that knows one provider's OAuth and asset model. The
framework owns everything provider-neutral:

* the connector interface (authorize URL with ``state`` and PKCE where the
  provider supports it, code exchange, long-lived upgrade, refresh, revoke,
  identity, connectable assets, token inspection and capabilities);
* a registry of live connectors plus the catalog of planned providers, which
  are always reported as ``coming_soon`` and can never be connected;
* OAuth ``state``/PKCE helpers;
* token sealing at rest through the repository's existing Fernet facility
  (``ai_runtime_service.encrypt_provider_secret``: SECRET_KEY-derived, with
  SECRET_KEY_PREVIOUS accepted for rotation).

Token values only ever live in memory inside ``TokenGrant`` and
``ConnectableAsset`` objects whose ``repr`` hides them, and in the encrypted
database columns. Nothing in this module logs or serializes a token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, runtime_checkable

from app.services import ai_runtime_service

# Providers that will arrive later as plug-in connectors on this framework.
# They are listed so the portal can show them honestly as "coming soon".
PLANNED_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("tiktok", "TikTok"),
    ("x", "X"),
    ("linkedin", "LinkedIn"),
    ("youtube", "YouTube"),
    ("snapchat", "Snapchat"),
    ("pinterest", "Pinterest"),
    ("whatsapp", "WhatsApp Business"),
)

SEALED_TOKEN_PREFIX = "fernet:v1:"


class SocialConnectorError(RuntimeError):
    """Fail-closed connector error with a stable, client-safe code.

    The message never contains a token, a secret or raw provider text.
    """

    def __init__(self, code: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderStatus:
    configured: bool
    reason: str | None = None


@dataclass(frozen=True)
class TokenGrant:
    access_token: str = field(repr=False)
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()
    refresh_token: str | None = field(default=None, repr=False)
    token_type: str = "bearer"


@dataclass(frozen=True)
class ProviderIdentity:
    external_id: str
    display_name: str
    avatar_url: str | None = None


@dataclass(frozen=True)
class TokenHealth:
    valid: bool
    expires_at: datetime | None
    scopes: tuple[str, ...]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConnectableAsset:
    """A Page/account the user may connect. ``access_token`` stays server-side."""

    provider: str
    account_kind: str
    external_id: str
    display_name: str
    handle: str | None = None
    avatar_url: str | None = None
    linked_external_id: str | None = None
    tasks: tuple[str, ...] = ()
    access_token: str | None = field(default=None, repr=False)

    @property
    def asset_id(self) -> str:
        return f"{self.provider}:{self.external_id}"

    def public(self) -> dict[str, Any]:
        """Client-safe shape: an explicit allow-list that excludes the token."""

        return {
            "asset_id": self.asset_id,
            "provider": self.provider,
            "account_kind": self.account_kind,
            "external_id": self.external_id,
            "display_name": self.display_name,
            "handle": self.handle,
            "avatar_url": self.avatar_url,
            "linked_external_id": self.linked_external_id,
            "tasks": list(self.tasks),
        }


@runtime_checkable
class SocialConnector(Protocol):
    """Interface every provider connector implements."""

    @property
    def key(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def account_providers(self) -> tuple[str, ...]: ...

    @property
    def supports_pkce(self) -> bool: ...

    @property
    def supports_refresh(self) -> bool: ...

    def status(self) -> ProviderStatus: ...

    def scopes(self) -> tuple[str, ...]: ...

    def capabilities(self) -> dict[str, tuple[str, ...]]: ...

    def authorize_url(
        self,
        *,
        state: str,
        code_challenge: str | None,
        extra_scopes: tuple[str, ...] = (),
    ) -> str: ...

    async def exchange_code(
        self, *, code: str, code_verifier: str | None
    ) -> TokenGrant: ...

    async def upgrade_token(self, grant: TokenGrant) -> TokenGrant: ...

    async def refresh(self, grant: TokenGrant) -> TokenGrant: ...

    async def revoke(self, *, access_token: str, external_user_id: str) -> bool: ...

    async def identity(self, access_token: str) -> ProviderIdentity: ...

    async def list_assets(self, access_token: str) -> list[ConnectableAsset]: ...

    async def inspect_token(self, access_token: str) -> TokenHealth: ...


ConnectorFactory = Callable[[], SocialConnector]
_REGISTRY: dict[str, ConnectorFactory] = {}


def register_connector(key: str, factory: ConnectorFactory) -> None:
    """Register (or replace) the factory for a live connector."""

    normalized = key.strip().lower()
    if not normalized or not normalized.isascii() or not normalized.replace("_", "").isalnum():
        raise ValueError("connector key must be a short ascii identifier")
    _REGISTRY[normalized] = factory


def registered_keys() -> tuple[str, ...]:
    _ensure_builtin_connectors()
    return tuple(sorted(_REGISTRY))


def get_connector(key: str) -> SocialConnector:
    _ensure_builtin_connectors()
    normalized = (key or "").strip().lower()
    factory = _REGISTRY.get(normalized)
    if factory is None:
        if normalized in {item for item, _label in PLANNED_PROVIDERS}:
            raise SocialConnectorError("provider-coming-soon", status_code=409)
        raise SocialConnectorError("unsupported-provider", status_code=404)
    return factory()


def _ensure_builtin_connectors() -> None:
    if "meta" in _REGISTRY:
        return
    # Imported lazily to keep the framework free of provider imports at load.
    from app.services.social_meta_provider import MetaConnector

    _REGISTRY.setdefault("meta", MetaConnector)


def provider_catalog() -> list[dict[str, Any]]:
    """Every live connector with its real configuration status, then planned ones."""

    items: list[dict[str, Any]] = []
    for key in registered_keys():
        connector = get_connector(key)
        status = connector.status()
        items.append(
            {
                "key": connector.key,
                "display_name": connector.display_name,
                "status": "configured" if status.configured else "not_configured",
                "reason": None if status.configured else status.reason,
                "connectable": status.configured,
                "account_providers": list(connector.account_providers),
                "scopes": list(connector.scopes()),
                "capabilities": {
                    name: list(values) for name, values in connector.capabilities().items()
                },
                "supports_pkce": connector.supports_pkce,
            }
        )
    for key, label in PLANNED_PROVIDERS:
        if key in _REGISTRY:
            continue
        items.append(
            {
                "key": key,
                "display_name": label,
                "status": "coming_soon",
                "reason": "connector-not-available-yet",
                "connectable": False,
                "account_providers": [],
                "scopes": [],
                "capabilities": {},
                "supports_pkce": False,
            }
        )
    return items


# --- OAuth state and PKCE (RFC 7636) -------------------------------------------------


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_browser_binding() -> str:
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    # 64 random bytes -> 86 URL-safe characters, inside RFC 7636's 43..128.
    return secrets.token_urlsafe(64)


def code_challenge_s256(verifier: str) -> str:
    if not 43 <= len(verifier) <= 128:
        raise SocialConnectorError("pkce-verifier-invalid")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest_matches(value: str | None, expected_digest: str) -> bool:
    if not value:
        return False
    return hmac.compare_digest(digest(value), expected_digest)


# --- Token sealing at rest ------------------------------------------------------------


def seal_token(value: str) -> str:
    """Encrypt a provider token with the repository's Fernet facility."""

    if not value or not value.strip():
        raise SocialConnectorError("token-missing")
    return ai_runtime_service.encrypt_provider_secret(value)


def open_token(ciphertext: str | None) -> str:
    """Decrypt a sealed provider token; fails closed when it is absent."""

    if not ciphertext:
        raise SocialConnectorError("token-not-available", status_code=409)
    value = ai_runtime_service.decrypt_provider_secret(ciphertext)
    if not value:
        raise SocialConnectorError("token-not-available", status_code=409)
    return value
