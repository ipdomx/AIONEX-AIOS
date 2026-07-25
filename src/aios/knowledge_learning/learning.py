from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .models import LearningEvent, Outcome
from .storage import HashChainedJsonl


class ExperienceLearningEngine:
    """Learns reusable lessons and blocks unchanged repeated failures."""

    def __init__(self, path: str | Path) -> None:
        self.store = HashChainedJsonl(path)

    @staticmethod
    def context_fingerprint(context: dict[str, Any]) -> str:
        canonical = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record(self, action: str, context: dict[str, Any], outcome: Outcome, evidence: tuple[str, ...],
               *, strategy: str | None = None, project: str | None = None,
               error_fingerprint: str | None = None, lesson: str | None = None) -> LearningEvent:
        if outcome in {Outcome.SUCCESS, Outcome.FAILURE} and not evidence:
            raise ValueError("evidence is required for decisive outcomes")
        event = LearningEvent(
            event_id=str(uuid.uuid4()), action=action,
            context_fingerprint=self.context_fingerprint(context), outcome=outcome,
            evidence=evidence, strategy=strategy, project=project,
            error_fingerprint=error_fingerprint, lesson=lesson,
        )
        self.store.append(event.to_dict())
        return event

    def guard(self, action: str, context: dict[str, Any]) -> tuple[str, ...]:
        fingerprint = self.context_fingerprint(context)
        failures = [p for p in self.store.payloads()
                    if p["action"] == action and p["context_fingerprint"] == fingerprint
                    and p["outcome"] == Outcome.FAILURE.value]
        successes = [p for p in self.store.payloads()
                     if p["action"] == action and p["context_fingerprint"] == fingerprint
                     and p["outcome"] == Outcome.SUCCESS.value]
        if failures and not successes:
            lessons = [item.get("lesson") or item.get("error_fingerprint") or "known failure" for item in failures]
            return tuple(dict.fromkeys(lessons))
        return ()

    def strategy_reputation(self, action: str) -> dict[str, float]:
        events = [p for p in self.store.payloads() if p["action"] == action and p.get("strategy")]
        totals = Counter(p["strategy"] for p in events)
        successes = Counter(p["strategy"] for p in events if p["outcome"] == Outcome.SUCCESS.value)
        return {strategy: successes[strategy] / total for strategy, total in totals.items()}

    def verify(self) -> bool:
        return self.store.verify()
