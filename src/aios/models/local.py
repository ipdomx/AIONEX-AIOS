from __future__ import annotations

from .base import ModelProvider, ModelResponse


class LocalPlaceholderProvider(ModelProvider):
    name = 'local'

    def __init__(self, model: str = 'local-placeholder'):
        self.model = model

    def generate(self, prompt: str, system: str | None = None) -> ModelResponse:
        return ModelResponse(
            text='لا يوجد نموذج محلي متصل بعد. تم حفظ الطلب ويمكن توصيل Ollama أو أي مزود محلي لاحقًا.',
            model=self.model,
            provider=self.name,
            confidence=0.1,
        )
