from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GateStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(slots=True)
class ReleaseGate:
    name: str
    required: bool = True
    status: GateStatus = GateStatus.PENDING
    details: str | None = None


@dataclass(slots=True)
class ReleaseGateReport:
    candidate_id: str
    gates: list[ReleaseGate] = field(default_factory=list)

    def add(self, gate: ReleaseGate) -> None:
        if any(existing.name == gate.name for existing in self.gates):
            raise ValueError(f"duplicate gate: {gate.name}")
        self.gates.append(gate)

    def mark(self, name: str, status: GateStatus, details: str | None = None) -> ReleaseGate:
        gate = next(g for g in self.gates if g.name == name)
        gate.status = status
        gate.details = details
        return gate

    @property
    def ready(self) -> bool:
        return all(
            gate.status is GateStatus.PASSED
            for gate in self.gates
            if gate.required
        )

    @property
    def failures(self) -> list[ReleaseGate]:
        return [gate for gate in self.gates if gate.status is GateStatus.FAILED]
