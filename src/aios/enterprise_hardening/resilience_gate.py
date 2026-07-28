from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ResilienceEvidence:
    owner_id: str
    backup_verified: bool = False
    restore_verified: bool = False
    failover_verified: bool = False
    disaster_recovery_verified: bool = False
    load_test_verified: bool = False
    security_validation_verified: bool = False
    notes: list[str] = field(default_factory=list)


class EnterpriseResilienceGate:
    REQUIRED = (
        "backup_verified",
        "restore_verified",
        "failover_verified",
        "disaster_recovery_verified",
        "load_test_verified",
        "security_validation_verified",
    )

    def validate(self, evidence: ResilienceEvidence) -> list[str]:
        return [name for name in self.REQUIRED if not getattr(evidence, name)]

    def assert_ready(self, evidence: ResilienceEvidence) -> None:
        missing = self.validate(evidence)
        if missing:
            raise RuntimeError("enterprise resilience gate failed: " + ", ".join(missing))
