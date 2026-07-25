from __future__ import annotations

from typing import Any

from ..models import ModelRequest, ModelResponse


class RequestNormalizer:
    @staticmethod
    def common(request: ModelRequest, model: str) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        return {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "metadata": dict(request.metadata),
        }


class ResponseNormalizer:
    @staticmethod
    def from_mapping(provider: str, model: str, payload: dict[str, Any]) -> ModelResponse:
        usage = payload.get("usage") or {}
        text = payload.get("text") or payload.get("output_text") or ""
        return ModelResponse(
            provider=provider,
            model=model,
            text=str(text),
            input_tokens=int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0),
            output_tokens=int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0),
            latency_ms=float(payload.get("latency_ms", 0.0) or 0.0),
            cost=float(payload.get("cost", 0.0) or 0.0),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            metadata={k: v for k, v in payload.items() if k not in {"text", "output_text", "usage"}},
        )
