from __future__ import annotations

import json
import urllib.request

from .base import ModelProvider, ModelResponse


class OpenAICompatibleProvider(ModelProvider):
    name = 'openai-compatible'

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str, system: str | None = None) -> ModelResponse:
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        payload = json.dumps({'model': self.model, 'messages': messages}).encode()
        request = urllib.request.Request(
            f'{self.base_url}/chat/completions',
            data=payload,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode())
        text = data['choices'][0]['message']['content']
        return ModelResponse(text=text, model=self.model, provider=self.name, confidence=0.7)
