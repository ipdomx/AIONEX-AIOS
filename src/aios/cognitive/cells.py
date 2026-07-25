from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import CellOpinion, Proposal, VoteChoice


class CognitiveCell(Protocol):
    id: str
    name: str
    domains: frozenset[str]
    weight: float

    def review(self, proposal: Proposal, round_number: int = 1) -> CellOpinion: ...


@dataclass(slots=True)
class RuleBasedCell:
    id: str
    name: str
    domains: frozenset[str]
    weight: float
    focus: str
    blocking_terms: tuple[str, ...] = ()
    caution_terms: tuple[str, ...] = ()

    def review(self, proposal: Proposal, round_number: int = 1) -> CellOpinion:
        text = f"{proposal.title} {proposal.description}".lower()
        blockers = tuple(term for term in self.blocking_terms if term in text)
        cautions = tuple(term for term in self.caution_terms if term in text)
        risks: list[str] = []
        conditions: list[str] = []

        if blockers:
            vote = VoteChoice.REJECT
            risks.append(f"Blocking indicators detected: {', '.join(blockers)}")
            confidence = 0.92
        elif cautions or proposal.risk_level in {"high", "critical"}:
            vote = VoteChoice.CONDITIONAL
            if cautions:
                risks.append(f"Risk indicators detected: {', '.join(cautions)}")
            conditions.extend(("Run in an isolated environment", "Provide rollback and verification evidence"))
            confidence = 0.84
        else:
            vote = VoteChoice.APPROVE
            confidence = 0.80

        if round_number > 1 and vote is VoteChoice.CONDITIONAL:
            conditions.append("Resolve objections recorded in the previous round")

        return CellOpinion(
            cell_id=self.id,
            summary=f"{self.name}: {self.focus}",
            evidence=(f"Reviewed proposal risk level: {proposal.risk_level}",),
            risks=tuple(risks),
            conditions=tuple(conditions),
            confidence=confidence,
            vote=vote,
            weight=self.weight,
        )


def default_cells() -> tuple[RuleBasedCell, ...]:
    destructive = ("delete", "drop", "rm -rf", "حذف", "مسح")
    live = ("production", "live", "مباشر", "الإنتاج")
    secrets = ("password", "secret", "token", "كلمة المرور", "مفتاح")
    return (
        RuleBasedCell("architecture", "Architecture Cell", frozenset({"architecture", "platform"}), 1.15,
                      "preserve modular boundaries and long-term extensibility", caution_terms=("rewrite", "monolith", "إعادة كتابة")),
        RuleBasedCell("security", "Security Cell", frozenset({"security", "governance"}), 1.35,
                      "enforce least privilege, traceability, and containment", blocking_terms=("disable security", "تجاوز الحماية"), caution_terms=destructive + secrets),
        RuleBasedCell("quality", "Quality Cell", frozenset({"testing", "quality"}), 1.10,
                      "require deterministic tests and regression coverage", caution_terms=("skip tests", "بدون اختبار")),
        RuleBasedCell("operations", "Operations Cell", frozenset({"deployment", "operations"}), 1.10,
                      "protect availability with backup, observability, and rollback", caution_terms=live + destructive),
        RuleBasedCell("data", "Data & Memory Cell", frozenset({"data", "memory"}), 1.05,
                      "protect durable knowledge, integrity, and migration safety", caution_terms=destructive),
        RuleBasedCell("research", "Research Cell", frozenset({"research", "verification"}), 0.90,
                      "separate verified evidence from assumptions", caution_terms=("assume", "تخمين")),
        RuleBasedCell("strategy", "Strategy Cell", frozenset({"product", "strategy"}), 1.00,
                      "verify value, scope, and institutional usability"),
        RuleBasedCell("governance", "Governance Cell", frozenset({"policy", "ethics"}), 1.30,
                      "require accountable human authority for consequential change", caution_terms=live + destructive),
        RuleBasedCell("performance", "Performance Cell", frozenset({"performance"}), 0.80,
                      "measure before optimization", caution_terms=("optimize everything", "تحسين كل شيء")),
        RuleBasedCell("self_evolution", "Self-Evolution Cell", frozenset({"self-update", "evolution"}), 1.25,
                      "allow proposals and sandboxed patches, never uncontrolled self-modification", blocking_terms=("self deploy without approval", "تطوير ونشر دون موافقة"), caution_terms=("self update", "يطور نفسه", "تطوير ذاتي")),
    )
