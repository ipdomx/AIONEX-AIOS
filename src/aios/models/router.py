from __future__ import annotations

import os

from .base import ModelProvider
from .local import LocalPlaceholderProvider
from .openai_compatible import OpenAICompatibleProvider


class ModelRouter:
    def build_default(self) -> ModelProvider:
        provider = os.environ.get('AIOS_MODEL_PROVIDER', 'local')
        model = os.environ.get('AIOS_MODEL_NAME', 'local-placeholder')
        if provider == 'openai-compatible':
            base_url = os.environ.get('AIOS_OPENAI_COMPAT_BASE_URL', '')
            api_key = os.environ.get('AIOS_OPENAI_COMPAT_API_KEY', '')
            if not base_url or not api_key:
                raise RuntimeError('OpenAI-compatible provider requires base URL and API key')
            return OpenAICompatibleProvider(base_url, api_key, model)
        return LocalPlaceholderProvider(model)
