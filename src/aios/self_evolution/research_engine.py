from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import EvidenceItem


@dataclass(slots=True)
class ResearchQuestion:
    question_id: str
    owner_id: str
    question: str
    sources: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ResearchEngine:
    def __init__(self) -> None:
        self._questions: dict[str, ResearchQuestion] = {}

    def open(self, question: ResearchQuestion) -> ResearchQuestion:
        if question.question_id in self._questions:
            raise ValueError(f"duplicate research question: {question.question_id}")
        self._questions[question.question_id] = question
        return question

    def add_source(self, question_id: str, owner_id: str, source: str) -> ResearchQuestion:
        question = self._require_owner(question_id, owner_id)
        if source not in question.sources:
            question.sources.append(source)
        return question

    def add_evidence(self, question_id: str, owner_id: str, evidence: EvidenceItem) -> ResearchQuestion:
        question = self._require_owner(question_id, owner_id)
        question.evidence.append(evidence)
        return question

    def confidence(self, question_id: str, owner_id: str) -> float:
        question = self._require_owner(question_id, owner_id)
        verified = [item.confidence for item in question.evidence if item.verified]
        if not verified:
            return 0.0
        return sum(verified) / len(verified)

    def _require_owner(self, question_id: str, owner_id: str) -> ResearchQuestion:
        question = self._questions[question_id]
        if question.owner_id != owner_id:
            raise PermissionError("research question is not owned by this owner")
        return question
