"""Provider-neutral Phase 36H SFU/TURN candidate contracts.

This module is deliberately source-only and network-free.  It defines the
provider boundary and validates immutable candidate configuration, but it does
not call LiveKit, Coturn, or any other external service.  Runtime activation is
a separate Phase 36H gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

LIVEKIT_SERVER_VERSION = "v1.13.5"
LIVEKIT_SERVER_AMD64_DIGEST = (
    "sha256:d0d1cfdbe95617647bbe91630454526c2cdd88cec83f41114b3495b444918b9a"
)
LIVEKIT_EGRESS_VERSION = "v1.13.0"
LIVEKIT_EGRESS_AMD64_DIGEST = (
    "sha256:a3e61a70479694a5075cff3c081ab633f34d3bfa778adc6089935c96908b6550"
)
COTURN_VERSION = "4.17.2"
COTURN_AMD64_DIGEST = (
    "sha256:75e9ebd1e19005bec0c7f591d29afe22f959916ac8d9c852452f27db8c789828"
)

_SECRET_REF_PREFIXES = ("env://", "file:///run/secrets/", "k8s-secret://")
_ALLOWED_ICE_SCHEMES = {"stun", "stuns", "turn", "turns"}
_ALLOWED_TURN_TRANSPORTS = {"udp", "tcp"}


class RealtimeMediaConfigurationError(ValueError):
    """The dormant realtime provider candidate configuration is unsafe."""


class RealtimeMediaDisabledError(RuntimeError):
    """A provider mutation was attempted before the explicit activation gate."""


def _secret_ref(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized.startswith(_SECRET_REF_PREFIXES):
        raise RealtimeMediaConfigurationError(
            f"{field} must be an env/file/k8s secret reference, never a raw secret"
        )
    if len(normalized) > 512:
        raise RealtimeMediaConfigurationError(f"{field} secret reference is too long")
    return normalized


def _secure_service_url(value: str, *, field: str, scheme: str) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme != scheme or not parsed.hostname:
        raise RealtimeMediaConfigurationError(
            f"{field} must use {scheme} with a concrete host"
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise RealtimeMediaConfigurationError(
            f"{field} must not contain credentials or fragments"
        )
    return normalized.rstrip("/")


def _ice_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in _ALLOWED_ICE_SCHEMES or not parsed.hostname:
        raise RealtimeMediaConfigurationError(
            "ICE URL must use stun/stuns/turn/turns with a concrete host"
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise RealtimeMediaConfigurationError(
            "ICE URL must not embed credentials or fragments"
        )
    if parsed.path not in {"", "/"}:
        raise RealtimeMediaConfigurationError("ICE URL must not contain a path")
    parameters = dict(parse_qsl(parsed.query, keep_blank_values=True))
    unknown = set(parameters) - {"transport"}
    if unknown:
        raise RealtimeMediaConfigurationError(
            "ICE URL only permits the standard transport query parameter"
        )
    transport = parameters.get("transport")
    if transport is not None and transport not in _ALLOWED_TURN_TRANSPORTS:
        raise RealtimeMediaConfigurationError("TURN transport must be udp or tcp")
    return normalized


def _opaque(value: str, *, prefix: str, length: int = 32) -> str:
    if not value.strip():
        raise RealtimeMediaConfigurationError("opaque identity input must not be empty")
    return prefix + sha256(value.encode("utf-8")).hexdigest()[:length]


@dataclass(frozen=True, slots=True)
class TurnServerReference:
    """Non-secret ICE endpoint metadata plus references to credential material."""

    urls: tuple[str, ...]
    username_ref: str | None = None
    credential_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.urls:
            raise RealtimeMediaConfigurationError("at least one ICE URL is required")
        normalized = tuple(_ice_url(item) for item in self.urls)
        object.__setattr__(self, "urls", normalized)
        needs_credential = any(
            urlsplit(item).scheme in {"turn", "turns"} for item in normalized
        )
        if needs_credential:
            if self.username_ref is None or self.credential_ref is None:
                raise RealtimeMediaConfigurationError(
                    "TURN endpoints require username and credential references"
                )
            object.__setattr__(
                self,
                "username_ref",
                _secret_ref(self.username_ref, field="TURN username"),
            )
            object.__setattr__(
                self,
                "credential_ref",
                _secret_ref(self.credential_ref, field="TURN credential"),
            )
        elif self.username_ref is not None or self.credential_ref is not None:
            raise RealtimeMediaConfigurationError(
                "STUN-only endpoints must not carry credential references"
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            "urls": list(self.urls),
            "username_reference_present": self.username_ref is not None,
            "credential_reference_present": self.credential_ref is not None,
            "raw_credential_returned": False,
        }


@dataclass(frozen=True, slots=True)
class LiveKitCandidateConfig:
    """Source-only LiveKit/Coturn candidate configuration."""

    signaling_url: str
    api_url: str
    api_key_ref: str
    api_secret_ref: str
    turn_servers: tuple[TurnServerReference, ...]
    enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "signaling_url",
            _secure_service_url(
                self.signaling_url, field="LiveKit signaling URL", scheme="wss"
            ),
        )
        object.__setattr__(
            self,
            "api_url",
            _secure_service_url(self.api_url, field="LiveKit API URL", scheme="https"),
        )
        object.__setattr__(
            self,
            "api_key_ref",
            _secret_ref(self.api_key_ref, field="LiveKit API key"),
        )
        object.__setattr__(
            self,
            "api_secret_ref",
            _secret_ref(self.api_secret_ref, field="LiveKit API secret"),
        )
        if not self.turn_servers:
            raise RealtimeMediaConfigurationError(
                "at least one explicit STUN/TURN server reference is required"
            )

    def safe_snapshot(self) -> dict[str, Any]:
        return {
            "provider": "livekit",
            "enabled": self.enabled,
            "signaling_url": self.signaling_url,
            "api_url": self.api_url,
            "api_key_reference_present": True,
            "api_secret_reference_present": True,
            "raw_api_key_returned": False,
            "raw_api_secret_returned": False,
            "turn_servers": [item.snapshot() for item in self.turn_servers],
            "livekit_server_version": LIVEKIT_SERVER_VERSION,
            "livekit_server_amd64_digest": LIVEKIT_SERVER_AMD64_DIGEST,
            "coturn_version": COTURN_VERSION,
            "coturn_amd64_digest": COTURN_AMD64_DIGEST,
            "egress_version": LIVEKIT_EGRESS_VERSION,
            "egress_amd64_digest": LIVEKIT_EGRESS_AMD64_DIGEST,
            "egress_activated": False,
        }


@dataclass(frozen=True, slots=True)
class SFURoomPlan:
    provider: str
    provider_room_name: str
    organization_fingerprint: str
    room_fingerprint: str
    signaling_url: str
    max_participants: int
    recording_enabled: bool
    provider_mutation_allowed: bool

    def safe_snapshot(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_room_name": self.provider_room_name,
            "organization_fingerprint": self.organization_fingerprint,
            "room_fingerprint": self.room_fingerprint,
            "signaling_url": self.signaling_url,
            "max_participants": self.max_participants,
            "recording_enabled": self.recording_enabled,
            "provider_mutation_allowed": self.provider_mutation_allowed,
        }


class SFUAdapter(Protocol):
    provider: str

    def candidate_snapshot(self) -> dict[str, Any]: ...

    def plan_room(
        self,
        *,
        organization_id: str,
        room_id: str,
        max_participants: int,
    ) -> SFURoomPlan: ...

    async def provision_room(self, plan: SFURoomPlan) -> None: ...


def build_livekit_room_plan(
    *,
    organization_id: str,
    room_id: str,
    max_participants: int,
    signaling_url: str,
    provider_mutation_allowed: bool,
) -> SFURoomPlan:
    """Build the deterministic LiveKit room identity used by candidate and runtime adapters."""
    if not 1 <= max_participants <= 10_000:
        raise RealtimeMediaConfigurationError(
            "room participant limit must be between 1 and 10000"
        )
    secure_signaling = _secure_service_url(
        signaling_url, field="LiveKit signaling URL", scheme="wss"
    )
    tenant_fingerprint = sha256(organization_id.encode("utf-8")).hexdigest()
    room_fingerprint = sha256(room_id.encode("utf-8")).hexdigest()
    provider_room_name = _opaque(
        f"{organization_id}\x00{room_id}", prefix="aios-rt-", length=40
    )
    return SFURoomPlan(
        provider="livekit",
        provider_room_name=provider_room_name,
        organization_fingerprint=tenant_fingerprint,
        room_fingerprint=room_fingerprint,
        signaling_url=secure_signaling,
        max_participants=max_participants,
        recording_enabled=False,
        provider_mutation_allowed=provider_mutation_allowed,
    )


class LiveKitCandidateAdapter:
    """Fail-closed LiveKit candidate adapter with zero network side effects."""

    provider = "livekit"

    def __init__(self, config: LiveKitCandidateConfig) -> None:
        self._config = config

    def candidate_snapshot(self) -> dict[str, Any]:
        return self._config.safe_snapshot()

    def plan_room(
        self,
        *,
        organization_id: str,
        room_id: str,
        max_participants: int,
    ) -> SFURoomPlan:
        return build_livekit_room_plan(
            organization_id=organization_id,
            room_id=room_id,
            max_participants=max_participants,
            signaling_url=self._config.signaling_url,
            provider_mutation_allowed=False,
        )

    async def provision_room(self, plan: SFURoomPlan) -> None:
        del plan
        if not self._config.enabled:
            raise RealtimeMediaDisabledError(
                "LiveKit provider mutations are disabled until the 36H activation gate"
            )
        raise RealtimeMediaDisabledError(
            "LiveKit runtime provisioning is intentionally not implemented in source-only 36H.3"
        )
