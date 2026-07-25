from __future__ import annotations

from .models import DeliveryDecision, GateResult, GateState


class DefinitionOfDoneEngine:
    DEFAULT_GATES = {
        "requirements": ("requirements_approved",),
        "implementation": ("build_passed", "code_reviewed"),
        "quality": ("tests_passed", "integration_passed"),
        "security": ("security_reviewed",),
        "operations": ("rollback_ready", "runbook_ready"),
        "documentation": ("documentation_complete",),
        "chief_engineer": ("chief_engineer_approved",),
        "owner": ("owner_approved",),
    }

    def evaluate(self, evidence: dict[str, object], required_gates: dict[str, tuple[str, ...]] | None = None) -> DeliveryDecision:
        gate_definitions = required_gates or self.DEFAULT_GATES
        results: list[GateResult] = []
        blockers: list[str] = []
        rework: list[str] = []
        for gate, requirements in gate_definitions.items():
            missing = tuple(key for key in requirements if not bool(evidence.get(key)))
            passed = not missing
            score = 100.0 * (len(requirements) - len(missing)) / max(1, len(requirements))
            results.append(GateResult(gate, GateState.PASSED if passed else GateState.FAILED, score, missing, evidence))
            for item in missing:
                blockers.append(f"{gate}:{item}")
                rework.append(f"Provide verified evidence for '{item}' in gate '{gate}'.")
        readiness = sum(result.score for result in results) / max(1, len(results))
        return DeliveryDecision(not blockers, round(readiness, 2), tuple(results), tuple(blockers), tuple(rework))
