from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ControlStatus(str, Enum):
    PLANNED = "planned"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(slots=True)
class ComplianceControl:
    control_id: str
    owner_id: str
    framework: str
    title: str
    status: ControlStatus = ControlStatus.PLANNED
    evidence: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ComplianceRegistry:
    def __init__(self) -> None:
        self._controls: dict[str, ComplianceControl] = {}

    def register(self, control: ComplianceControl) -> ComplianceControl:
        if control.control_id in self._controls:
            raise ValueError(f"duplicate compliance control: {control.control_id}")
        self._controls[control.control_id] = control
        return control

    def add_evidence(self, control_id: str, owner_id: str, reference: str) -> ComplianceControl:
        control = self._require_owner(control_id, owner_id)
        if reference not in control.evidence:
            control.evidence.append(reference)
        control.updated_at = datetime.now(timezone.utc)
        return control

    def set_status(self, control_id: str, owner_id: str, status: ControlStatus) -> ComplianceControl:
        control = self._require_owner(control_id, owner_id)
        if status is ControlStatus.VERIFIED and not control.evidence:
            raise ValueError("verified controls require evidence")
        control.status = status
        control.updated_at = datetime.now(timezone.utc)
        return control

    def report(self, owner_id: str) -> dict[str, int]:
        result = {status.value: 0 for status in ControlStatus}
        for control in self._controls.values():
            if control.owner_id == owner_id:
                result[control.status.value] += 1
        return result

    def _require_owner(self, control_id: str, owner_id: str) -> ComplianceControl:
        control = self._controls[control_id]
        if control.owner_id != owner_id:
            raise PermissionError("compliance control is not owned by this owner")
        return control
