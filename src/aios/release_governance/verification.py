from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class VerificationEvidence:
    evidence_id: str
    release_id: str
    evidence_type: str
    passed: bool
    source: str
    summary: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)


class VerificationRegistry:
    def __init__(self) -> None:
        self._evidence: dict[str, VerificationEvidence] = {}

    def add(self, evidence: VerificationEvidence) -> VerificationEvidence:
        if not evidence.evidence_id.strip() or not evidence.release_id.strip():
            raise ValueError("evidence_id and release_id are required")
        if not evidence.evidence_type.strip() or not evidence.source.strip():
            raise ValueError("evidence_type and source are required")
        if evidence.evidence_id in self._evidence:
            raise ValueError(f"duplicate evidence_id: {evidence.evidence_id}")
        self._evidence[evidence.evidence_id] = evidence
        return evidence

    def list_for_release(self, release_id: str) -> list[VerificationEvidence]:
        return [item for item in self._evidence.values() if item.release_id == release_id]

    def passed(self, release_id: str, required_types: set[str] | None = None) -> bool:
        evidence = self.list_for_release(release_id)
        if not evidence:
            return False
        required = set(required_types or set())
        by_type = {item.evidence_type: item for item in evidence}
        if any(item.evidence_type in required and not item.passed for item in evidence):
            return False
        if required and not required.issubset(by_type):
            return False
        return all(item.passed for item in evidence if not required or item.evidence_type in required)
