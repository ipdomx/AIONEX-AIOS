from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StableGateName(str, Enum):
    UNIT_TESTS = "unit_tests"
    INTEGRATION_TESTS = "integration_tests"
    SECURITY = "security"
    PERFORMANCE = "performance"
    MIGRATIONS = "migrations"
    BACKUP_RESTORE = "backup_restore"
    ROLLBACK = "rollback"
    DOCUMENTATION = "documentation"


@dataclass(slots=True, frozen=True)
class StableGateResult:
    name: StableGateName
    passed: bool
    details: str = ""


@dataclass(slots=True, frozen=True)
class StableReleaseDecision:
    approved: bool
    missing: tuple[StableGateName, ...]
    failed: tuple[StableGateName, ...]


class StableReleaseGate:
    REQUIRED = tuple(StableGateName)

    def evaluate(self, results: list[StableGateResult]) -> StableReleaseDecision:
        by_name = {result.name: result for result in results}
        missing = tuple(name for name in self.REQUIRED if name not in by_name)
        failed = tuple(
            name for name in self.REQUIRED if name in by_name and not by_name[name].passed
        )
        return StableReleaseDecision(
            approved=not missing and not failed,
            missing=missing,
            failed=failed,
        )
