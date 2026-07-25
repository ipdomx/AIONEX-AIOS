from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntegrationKind(str, Enum):
    SSH = "ssh"
    SOURCE_CONTROL = "source_control"
    CONTAINER = "container"
    ORCHESTRATION = "orchestration"
    CLOUD = "cloud"
    DATABASE = "database"
    DNS = "dns"
    STORAGE = "storage"
    SECRETS = "secrets"
    GENERIC = "generic"


class ConnectionState(str, Enum):
    UNKNOWN = "unknown"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class IntegrationCapability:
    name: str
    description: str = ""
    destructive: bool = False


@dataclass(frozen=True, slots=True)
class IntegrationDescriptor:
    name: str
    kind: IntegrationKind
    version: str = "1"
    capabilities: tuple[IntegrationCapability, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectionProfile:
    name: str
    integration: str
    endpoint: str | None = None
    credential_ref: str | None = None
    secret_refs: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class HealthReport:
    integration: str
    state: ConnectionState
    latency_ms: float | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Credential:
    username: str | None = None
    token: str | None = None
    password: str | None = None
    private_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def redacted(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "token": "***" if self.token else None,
            "password": "***" if self.password else None,
            "private_key": "***" if self.private_key else None,
            "metadata": dict(self.metadata),
        }
