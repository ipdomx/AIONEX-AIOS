from __future__ import annotations

from .models import DecisionOption, WisdomDecision


class LongTermWisdomEngine:
    """Selects durable options and abstains when evidence or safety is insufficient."""

    WEIGHTS = {
        "evidence_strength": 0.20,
        "reliability": 0.15,
        "security": 0.15,
        "maintainability": 0.12,
        "reversibility": 0.10,
        "long_term_value": 0.18,
        "cost_efficiency": 0.10,
    }

    def decide(self, options: tuple[DecisionOption, ...], minimum_score: float = 0.68) -> WisdomDecision:
        if not options:
            return WisdomDecision(None, 0.0, True, "No decision options were supplied.", ())
        ranking = []
        conditions: list[str] = []
        for option in options:
            score = sum(getattr(option, field) * weight for field, weight in self.WEIGHTS.items())
            score -= option.risk * 0.28
            ranking.append((option.option_id, max(0.0, min(1.0, score))))
        ranking.sort(key=lambda item: item[1], reverse=True)
        selected_id, score = ranking[0]
        selected = next(item for item in options if item.option_id == selected_id)
        if selected.evidence_strength < 0.65:
            conditions.append("Collect stronger evidence before execution.")
        if selected.reversibility < 0.5:
            conditions.append("Create and verify a rollback plan.")
        if selected.security < 0.6:
            conditions.append("Obtain security approval.")
        abstained = score < minimum_score or bool(conditions and selected.evidence_strength < 0.65)
        rationale = (
            "Abstained because the option did not meet the durable-decision gate."
            if abstained else
            "Selected the highest long-term value option after evidence, safety, reliability and reversibility scoring."
        )
        return WisdomDecision(None if abstained else selected_id, score, abstained, rationale,
                              tuple(ranking), tuple(conditions))
