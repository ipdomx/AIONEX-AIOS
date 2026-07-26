from __future__ import annotations

from dataclasses import dataclass

from .approvals import ReleaseApprovalBoard
from .artifacts import ArtifactRegistry
from .gates import ReleaseGateEngine
from .promotion import ReleasePromotionManager
from .releases import ReleaseStore
from .verification import VerificationRegistry


@dataclass
class ReleaseGovernancePlatform:
    releases: ReleaseStore
    approvals: ReleaseApprovalBoard
    gates: ReleaseGateEngine
    artifacts: ArtifactRegistry
    verification: VerificationRegistry
    promotion: ReleasePromotionManager

    @classmethod
    def build_default(cls) -> "ReleaseGovernancePlatform":
        return cls(
            releases=ReleaseStore(),
            approvals=ReleaseApprovalBoard(),
            gates=ReleaseGateEngine(),
            artifacts=ArtifactRegistry(),
            verification=VerificationRegistry(),
            promotion=ReleasePromotionManager(),
        )

    def readiness(self, release_id: str, required_evidence: set[str] | None = None) -> dict[str, bool]:
        checks = {
            "release_exists": True,
            "gates_passed": self.gates.passed(release_id),
            "approvals_complete": self.approvals.is_approved(release_id),
            "verification_passed": self.verification.passed(release_id, required_evidence),
            "artifact_present": bool(self.artifacts.list_for_release(release_id)),
        }
        try:
            self.releases.get(release_id)
        except LookupError:
            checks["release_exists"] = False
        checks["ready"] = all(checks.values())
        return checks

    def validate(self) -> dict[str, bool]:
        checks = {
            "release_store": self.releases is not None,
            "approval_board": self.approvals is not None,
            "gate_engine": self.gates is not None,
            "artifact_registry": self.artifacts is not None,
            "verification_registry": self.verification is not None,
            "promotion_manager": self.promotion is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
