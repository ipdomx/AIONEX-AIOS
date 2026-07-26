from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    passed: bool
    message: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ReleaseGate:
    gate_id: str
    description: str
    check: Callable[[str], tuple[bool, str]]
    required: bool = True


class ReleaseGateEngine:
    def __init__(self) -> None:
        self._gates: dict[str, ReleaseGate] = {}
        self._results: dict[str, list[GateResult]] = {}

    def register(self, gate: ReleaseGate) -> ReleaseGate:
        if not gate.gate_id.strip():
            raise ValueError("gate_id is required")
        self._gates[gate.gate_id] = gate
        return gate

    def evaluate(self, release_id: str) -> list[GateResult]:
        if not release_id.strip():
            raise ValueError("release_id is required")
        results: list[GateResult] = []
        for gate in self._gates.values():
            passed, message = gate.check(release_id)
            results.append(GateResult(gate.gate_id, bool(passed), str(message)))
        self._results[release_id] = results
        return list(results)

    def results_for(self, release_id: str) -> list[GateResult]:
        return list(self._results.get(release_id, []))

    def passed(self, release_id: str) -> bool:
        results = {result.gate_id: result for result in self.results_for(release_id)}
        for gate in self._gates.values():
            if not gate.required:
                continue
            result = results.get(gate.gate_id)
            if result is None or not result.passed:
                return False
        return True
