from __future__ import annotations

import json
from dataclasses import dataclass

from .db import Database
from .memory import MemoryStore


@dataclass(slots=True)
class Decision:
    recommendation: str
    alternatives: list[str]
    risks: list[str]
    confidence: float
    approval_required: bool = True


class DecisionEngine:
    def __init__(self, db: Database, memory: MemoryStore):
        self.db = db
        self.memory = memory

    def evaluate(self, request: str, project: str | None = None) -> Decision:
        normalized = request.lower()
        risks: list[str] = []
        alternatives: list[str] = []

        if any(word in normalized for word in ('delete', 'حذف', 'drop', 'rm ')):
            risks.append('Potentially destructive operation')
            alternatives.append('Archive or snapshot before deletion')
        if any(word in normalized for word in ('production', 'live', 'حقيقي', 'مباشر')):
            risks.append('Live-environment impact')
            alternatives.append('Use an isolated workspace first')
        prior_failures = self.memory.find_failures(request[:40], project)
        if prior_failures:
            risks.append('Similar failure exists in project memory')
            alternatives.append('Review the verified prior fix before implementation')
        if not alternatives:
            alternatives.append('Implement in an isolated workspace and run regression checks')

        confidence = 0.78 if risks else 0.88
        recommendation = (
            'لا تنفذ مباشرة. جهّز خطة قابلة للتراجع أولًا.'
            if risks else
            'يمكن المتابعة داخل مساحة معزولة مع اختبارات ومراجعة.'
        )
        with self.db.connect() as conn:
            conn.execute(
                '''INSERT INTO decisions(project, request, recommendation, alternatives, risks, confidence)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (project, request, recommendation, json.dumps(alternatives, ensure_ascii=False),
                 json.dumps(risks, ensure_ascii=False), confidence),
            )
        return Decision(recommendation, alternatives, risks, confidence)
