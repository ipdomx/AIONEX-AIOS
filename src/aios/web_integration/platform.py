from __future__ import annotations

from dataclasses import dataclass

from .gateway import DashboardGateway
from .registry import DashboardRegistry
from .sessions import DashboardSessionManager
from .tokens import DashboardTokenService


@dataclass
class WebIntegrationFoundation:
    registry: DashboardRegistry
    tokens: DashboardTokenService
    sessions: DashboardSessionManager
    gateway: DashboardGateway

    @classmethod
    def build_default(cls, secret: str | None = None) -> "WebIntegrationFoundation":
        registry = DashboardRegistry()
        tokens = DashboardTokenService(secret=secret)
        sessions = DashboardSessionManager()
        gateway = DashboardGateway(registry, sessions, tokens)
        return cls(registry=registry, tokens=tokens, sessions=sessions, gateway=gateway)

    def validate(self) -> dict[str, bool]:
        checks = {
            "dashboard_registry": self.registry is not None,
            "token_service": self.tokens is not None,
            "session_manager": self.sessions is not None,
            "gateway": self.gateway is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
