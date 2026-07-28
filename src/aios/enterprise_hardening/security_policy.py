from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SecurityLevel(str, Enum):
    STANDARD = "standard"
    ELEVATED = "elevated"
    CRITICAL = "critical"


@dataclass(slots=True)
class SecurityPolicy:
    owner_id: str
    level: SecurityLevel = SecurityLevel.STANDARD
    require_mfa: bool = True
    require_signed_artifacts: bool = True
    allow_public_network_access: bool = False
    allowed_regions: set[str] = field(default_factory=set)
    blocked_services: set[str] = field(default_factory=set)


class SecurityPolicyEngine:
    def __init__(self) -> None:
        self._policies: dict[str, SecurityPolicy] = {}

    def set_policy(self, policy: SecurityPolicy) -> SecurityPolicy:
        self._policies[policy.owner_id] = policy
        return policy

    def get_policy(self, owner_id: str) -> SecurityPolicy:
        return self._policies.get(owner_id, SecurityPolicy(owner_id=owner_id))

    def assert_service_allowed(self, owner_id: str, service: str) -> None:
        policy = self.get_policy(owner_id)
        if service in policy.blocked_services:
            raise PermissionError(f"service blocked by enterprise policy: {service}")

    def assert_region_allowed(self, owner_id: str, region: str) -> None:
        policy = self.get_policy(owner_id)
        if policy.allowed_regions and region not in policy.allowed_regions:
            raise PermissionError(f"region not allowed by enterprise policy: {region}")
