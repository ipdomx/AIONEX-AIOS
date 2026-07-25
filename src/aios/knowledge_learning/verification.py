from __future__ import annotations

from collections import defaultdict

from .models import ResearchClaim, VerificationResult


class ResearchVerificationEngine:
    """Scores claims using source quality, corroboration, recency and direct evidence."""

    def verify(self, claim: str, supporting: tuple[ResearchClaim, ...],
               conflicting: tuple[ResearchClaim, ...] = (), threshold: float = 0.72) -> VerificationResult:
        if not supporting:
            return VerificationResult(claim, 0.0, False, tuple(item.source for item in conflicting), (),
                                      "No supporting evidence was supplied.")
        unique_sources = {item.source for item in supporting}
        weighted = []
        for item in supporting:
            direct = 1.0 if item.direct_evidence else 0.75
            corroboration = min(1.0, 0.55 + 0.15 * item.corroboration)
            weighted.append(item.source_quality * item.recency * direct * corroboration)
        support_score = sum(weighted) / len(weighted)
        diversity_bonus = min(0.12, max(0, len(unique_sources) - 1) * 0.04)
        conflict_penalty = min(0.45, sum(item.source_quality for item in conflicting) / max(1, len(conflicting)) * 0.45)
        confidence = max(0.0, min(1.0, support_score + diversity_bonus - conflict_penalty))
        accepted = confidence >= threshold and len(unique_sources) >= 2 and not (
            conflicting and max(item.source_quality for item in conflicting) >= 0.9
        )
        rationale = (
            f"support={support_score:.3f}; source_diversity={len(unique_sources)}; "
            f"conflict_penalty={conflict_penalty:.3f}; threshold={threshold:.2f}"
        )
        return VerificationResult(
            claim=claim, confidence=confidence, accepted=accepted,
            conflicts=tuple(item.source for item in conflicting),
            evidence_sources=tuple(sorted(unique_sources)), rationale=rationale,
        )
