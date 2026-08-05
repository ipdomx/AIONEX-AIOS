from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class KnowledgeFinding:
    finding_id: str
    owner_id: str
    topic: str
    statement: str
    confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeSynthesisService:
    def __init__(self) -> None:
        self._findings: dict[str, KnowledgeFinding] = {}

    def publish(self, finding: KnowledgeFinding) -> KnowledgeFinding:
        if not 0.0 <= finding.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not finding.evidence_ids:
            raise ValueError("at least one evidence item is required")
        if finding.finding_id in self._findings:
            raise ValueError(f"duplicate finding: {finding.finding_id}")
        self._findings[finding.finding_id] = finding
        return finding

    def list_for_owner(self, owner_id: str, *, minimum_confidence: float = 0.0) -> list[KnowledgeFinding]:
        return sorted(
            (
                finding
                for finding in self._findings.values()
                if finding.owner_id == owner_id and finding.confidence >= minimum_confidence
            ),
            key=lambda finding: (finding.confidence, finding.created_at),
            reverse=True,
        )
