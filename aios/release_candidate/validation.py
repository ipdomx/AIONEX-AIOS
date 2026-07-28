from __future__ import annotations

from dataclasses import dataclass

from .gates import GateStatus, ReleaseGate, ReleaseGateReport
from .models import ReleaseCandidate


@dataclass(slots=True)
class ValidationInput:
    unit_tests_passed: bool
    integration_tests_passed: bool
    security_scan_passed: bool
    migration_check_passed: bool
    rollback_verified: bool
    documentation_complete: bool


class ReleaseCandidateValidator:
    REQUIRED_GATES = (
        "unit-tests",
        "integration-tests",
        "security-scan",
        "migration-check",
        "rollback-verification",
        "documentation",
    )

    def validate(self, candidate: ReleaseCandidate, inputs: ValidationInput) -> ReleaseGateReport:
        report = ReleaseGateReport(candidate_id=candidate.candidate_id)
        for name in self.REQUIRED_GATES:
            report.add(ReleaseGate(name=name))

        values = {
            "unit-tests": inputs.unit_tests_passed,
            "integration-tests": inputs.integration_tests_passed,
            "security-scan": inputs.security_scan_passed,
            "migration-check": inputs.migration_check_passed,
            "rollback-verification": inputs.rollback_verified,
            "documentation": inputs.documentation_complete,
        }
        for name, passed in values.items():
            report.mark(name, GateStatus.PASSED if passed else GateStatus.FAILED)

        if report.ready:
            candidate.approve()
        else:
            candidate.block(", ".join(gate.name for gate in report.failures))
        return report
