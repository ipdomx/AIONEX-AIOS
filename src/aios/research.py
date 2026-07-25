from __future__ import annotations

from .memory import MemoryStore


class ResearchStore:
    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def save(self, title: str, summary: str, source: str, project: str | None = None, confidence: float = 0.8) -> int:
        return self.memory.remember(
            content=f'{title}\n\n{summary}',
            kind='research',
            project=project,
            source=source,
            confidence=confidence,
            verified=False,
        )
