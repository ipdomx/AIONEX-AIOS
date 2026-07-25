from __future__ import annotations

from pathlib import Path
from typing import Any

from .graph import EnterpriseKnowledgeGraph
from .learning import ExperienceLearningEngine
from .memory import EnterpriseMemory
from .models import (
    DecisionOption, KnowledgeItem, MemoryScope, Outcome, Provenance,
    ResearchClaim, VerificationResult, WisdomDecision,
)
from .verification import ResearchVerificationEngine
from .wisdom import LongTermWisdomEngine


class KnowledgeLearningPlatform:
    """Facade for persistent memory, graph knowledge, learning, verification and wisdom."""

    def __init__(self, root: str | Path) -> None:
        root = Path(root)
        self.memory = EnterpriseMemory(root / "memory")
        self.graph = EnterpriseKnowledgeGraph(root / "graph")
        self.experience = ExperienceLearningEngine(root / "learning-events.jsonl")
        self.verification = ResearchVerificationEngine()
        self.wisdom = LongTermWisdomEngine()

    def learn_fact(self, scope: MemoryScope, owner: str, namespace: str, subject: str, content: Any,
                   *, confidence: float, sources: tuple[str, ...], tags: tuple[str, ...] = (),
                   verified: bool = False) -> KnowledgeItem:
        provenance = tuple(Provenance(source=source, source_type="verified" if verified else "reported")
                           for source in sources)
        item = self.memory.remember(scope, owner, namespace, subject, content, confidence=confidence,
                                    provenance=provenance, tags=tags, verified=verified)
        self.graph.upsert_node(item.item_id, "knowledge", subject=subject, namespace=namespace,
                               confidence=confidence, verified=verified)
        return item

    def record_outcome(self, action: str, context: dict[str, Any], outcome: Outcome,
                       evidence: tuple[str, ...], **kwargs: Any):
        return self.experience.record(action, context, outcome, evidence, **kwargs)

    def verify_claim(self, claim: str, supporting: tuple[ResearchClaim, ...],
                     conflicting: tuple[ResearchClaim, ...] = ()) -> VerificationResult:
        return self.verification.verify(claim, supporting, conflicting)

    def decide(self, options: tuple[DecisionOption, ...]) -> WisdomDecision:
        return self.wisdom.decide(options)

    def health(self) -> dict[str, bool]:
        return {
            "graph_ledger": self.graph.verify(),
            "experience_ledger": self.experience.verify(),
        }
