from __future__ import annotations

from dataclasses import dataclass

from .gateway import APIExperienceGateway
from .middleware import CorrelationMiddleware
from .rate_limits import RateLimiter
from .registry import APIRegistry


@dataclass
class APIExperiencePlatform:
    registry: APIRegistry
    limiter: RateLimiter
    middleware: CorrelationMiddleware
    gateway: APIExperienceGateway

    @classmethod
    def build_default(cls) -> "APIExperiencePlatform":
        registry = APIRegistry()
        limiter = RateLimiter()
        middleware = CorrelationMiddleware()
        gateway = APIExperienceGateway(registry, limiter)
        return cls(
            registry=registry,
            limiter=limiter,
            middleware=middleware,
            gateway=gateway,
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "api_registry": self.registry is not None,
            "rate_limiter": self.limiter is not None,
            "correlation_middleware": self.middleware is not None,
            "api_gateway": self.gateway is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
