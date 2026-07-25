from __future__ import annotations

from collections import Counter

from .models import CandidateResult
from ..models import ModelResponse


class BestResultSelector:
    @staticmethod
    def select(results: tuple[CandidateResult, ...]) -> ModelResponse:
        successful = [item.response for item in results if item.successful and item.response is not None]
        if not successful:
            raise RuntimeError("no successful model result")
        return max(successful, key=lambda item: (item.confidence, len(item.text), -item.cost, -item.latency_ms))


class VotingEngine:
    @staticmethod
    def select(results: tuple[CandidateResult, ...]) -> ModelResponse:
        successful = [item.response for item in results if item.successful and item.response is not None]
        if not successful:
            raise RuntimeError("no successful model result")
        normalized = [" ".join(item.text.lower().split()) for item in successful]
        winner, _ = Counter(normalized).most_common(1)[0]
        matches = [item for item, text in zip(successful, normalized) if text == winner]
        return max(matches, key=lambda item: item.confidence)


class ConsensusEngine:
    @staticmethod
    def synthesize(results: tuple[CandidateResult, ...]) -> ModelResponse:
        selected = BestResultSelector.select(results)
        successful = [item.response for item in results if item.successful and item.response is not None]
        agreement = sum(1 for item in successful if item.text.strip().lower() == selected.text.strip().lower())
        confidence = min(1.0, max(selected.confidence, agreement / max(1, len(successful))))
        return ModelResponse(provider=selected.provider, model=selected.model, text=selected.text,
                             input_tokens=sum(item.input_tokens for item in successful),
                             output_tokens=sum(item.output_tokens for item in successful),
                             latency_ms=max(item.latency_ms for item in successful),
                             cost=sum(item.cost for item in successful), confidence=confidence,
                             metadata={**selected.metadata, "consensus_size": len(successful),
                                       "agreement_count": agreement})
