from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class ModelResponse:
    text: str
    model: str
    provider: str
    confidence: float = 0.5


class ModelProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None) -> ModelResponse:
        raise NotImplementedError
