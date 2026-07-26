from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import AutonomousDecision


@dataclass(frozen=True)
class AutonomyAuditRecord:
    decision_id: str
    event: str
    actor: str
    details: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AutonomyAuditLog:
    def __init__(self) -> None:
        self._records: list[AutonomyAuditRecord] = []

    def record(self, record: AutonomyAuditRecord) -> AutonomyAuditRecord:
        if not record.decision_id.strip() or not record.event.strip() or not record.actor.strip():
            raise ValueError("decision_id, event, and actor are required")
        self._records.append(record)
        return record

    def record_decision(self, decision: AutonomousDecision, event: str, actor: str) -> AutonomyAuditRecord:
        return self.record(
            AutonomyAuditRecord(
                decision_id=decision.decision_id,
                event=event,
                actor=actor,
                details={
                    "policy_id": decision.policy_id,
                    "action": decision.action,
                    "status": decision.status.value,
                    "risk_score": f"{decision.risk_score:.4f}",
                },
            )
        )

    def list_for_decision(self, decision_id: str) -> list[AutonomyAuditRecord]:
        return [record for record in self._records if record.decision_id == decision_id]

    def count(self) -> int:
        return len(self._records)
