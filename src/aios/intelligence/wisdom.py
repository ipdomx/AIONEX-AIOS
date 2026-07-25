from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True, frozen=True)
class Strategy:
    name: str
    expected_value: float
    evidence_quality: float
    reversibility: float
    maintainability: float
    security: float
    cost: float
    complexity: float
    future_value: float
    notes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class WisdomDecision:
    selected: Strategy | None
    ranking: tuple[tuple[str, float], ...]
    confidence: float
    rationale: str
    abstained: bool


class WisdomEngine:
    WEIGHTS = {
        'expected_value': 0.18, 'evidence_quality': 0.18, 'reversibility': 0.12,
        'maintainability': 0.14, 'security': 0.16, 'future_value': 0.14,
        'cost': -0.04, 'complexity': -0.04,
    }

    def decide(self, strategies: Iterable[Strategy], minimum_evidence: float = 0.55) -> WisdomDecision:
        items = tuple(strategies)
        if not items:
            return WisdomDecision(None, (), 0.0, 'No strategies were supplied', True)
        scored = [(item, self._score(item)) for item in items]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        best, score = scored[0]
        ranking = tuple((item.name, round(value, 4)) for item, value in scored)
        evidence = best.evidence_quality
        if evidence < minimum_evidence:
            return WisdomDecision(None, ranking, evidence, 'Insufficient evidence; more research or experiments required', True)
        margin = score - scored[1][1] if len(scored) > 1 else score
        confidence = max(0.0, min(1.0, (evidence * 0.65) + (max(0.0, margin) * 0.35)))
        rationale = (
            f'{best.name} offers the strongest long-term balance of evidence, security, '
            f'maintainability, reversibility, and future value.'
        )
        return WisdomDecision(best, ranking, confidence, rationale, False)

    def _score(self, strategy: Strategy) -> float:
        return sum(getattr(strategy, field) * weight for field, weight in self.WEIGHTS.items())
