"""Exact provider transport for Phase 36G private segment translation.

This module performs one synchronous translation request and never retries. Durable
arming, tenancy, lease/fencing, ambiguity handling, private storage and public
redaction are owned by :mod:`audio_dubbing_runtime`.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import httpx

_OPENAI_TRANSLATION_MODEL = "gpt-5.6-luna"
_OPENAI_INPUT_USD_PER_MILLION = 0.20
_OPENAI_OUTPUT_USD_PER_MILLION = 1.20
_MAX_SEGMENTS = 16
_MAX_SEGMENT_CHARACTERS = 4_000
_MAX_TOTAL_CHARACTERS = 80_000


@dataclass(frozen=True, slots=True)
class DubbingTranslationSourceSegment:
    segment_id: str
    speaker_key: str
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class ProviderDubbingTranslationRequest:
    provider: str
    model: str
    source_language: str
    target_language: str
    segments: tuple[DubbingTranslationSourceSegment, ...]
    max_output_tokens: int = 4_096


@dataclass(frozen=True, slots=True)
class ProviderDubbingTranslationResult:
    translations: dict[str, str]
    request_id: str | None
    metadata: dict[str, Any]
    usage: dict[str, Any]
    actual_cost_usd: float | None
    cost_basis: str


class ProviderDubbingTranslationFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        safe_to_resubmit: bool = False,
        ambiguous_submission: bool = False,
        http_status: int | None = None,
        metadata: dict[str, Any] | None = None,
        message: str = "Dubbing translation provider request failed",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.safe_to_resubmit = safe_to_resubmit
        self.ambiguous_submission = ambiguous_submission
        self.http_status = http_status
        self.metadata = metadata or {}


def estimate_openai_translation_cost(
    *,
    source_characters: int,
    segment_count: int,
) -> tuple[float, dict[str, Any]]:
    """Return a conservative source estimate, never a claimed bill.

    The estimate intentionally includes schema/instruction overhead and permits
    translated text to expand. Live completion replaces it with usage-token cost
    only when the provider returns authoritative usage.
    """
    if not 1 <= source_characters <= _MAX_TOTAL_CHARACTERS:
        raise ProviderDubbingTranslationFailure(
            "provider_pricing_unknown", retryable=False
        )
    if not 1 <= segment_count <= _MAX_SEGMENTS:
        raise ProviderDubbingTranslationFailure(
            "provider_pricing_unknown", retryable=False
        )
    estimated_input_tokens = math.ceil((source_characters + 600 + segment_count * 40) / 3.5)
    estimated_output_tokens = math.ceil((source_characters * 1.6 + 300) / 3.5)
    estimate = round(
        estimated_input_tokens * _OPENAI_INPUT_USD_PER_MILLION / 1_000_000
        + estimated_output_tokens * _OPENAI_OUTPUT_USD_PER_MILLION / 1_000_000,
        9,
    )
    return estimate, {
        "schema": "36G.dubbing-translation-pricing.v1",
        "model": _OPENAI_TRANSLATION_MODEL,
        "pricing_revision": "2026-08-23",
        "input_usd_per_million_tokens": _OPENAI_INPUT_USD_PER_MILLION,
        "output_usd_per_million_tokens": _OPENAI_OUTPUT_USD_PER_MILLION,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimate_only": True,
        "authoritative_usage_required_for_actual_cost": True,
    }


def _safe_error_metadata(response: httpx.Response) -> dict[str, Any]:
    safe: dict[str, Any] = {"http_status": response.status_code}
    try:
        payload = response.json()
    except ValueError:
        return safe
    if not isinstance(payload, dict):
        return safe
    raw_error = payload.get("error")
    error = raw_error if isinstance(raw_error, dict) else payload
    if not isinstance(error, dict):
        return safe
    for key in ("type", "code", "param"):
        value = error.get(key)
        if isinstance(value, (str, int, float, bool)):
            safe[key] = str(value)[:160]
    return safe


def _failure_for_response(response: httpx.Response) -> ProviderDubbingTranslationFailure:
    status = response.status_code
    metadata = _safe_error_metadata(response)
    if status in {401, 403}:
        return ProviderDubbingTranslationFailure(
            "provider_auth", retryable=False, http_status=status, metadata=metadata
        )
    if status == 402:
        return ProviderDubbingTranslationFailure(
            "provider_billing", retryable=False, http_status=status, metadata=metadata
        )
    if status == 429:
        return ProviderDubbingTranslationFailure(
            "provider_rate_limited",
            retryable=True,
            safe_to_resubmit=True,
            http_status=status,
            metadata=metadata,
        )
    if status in {400, 404, 409, 413, 415, 422}:
        return ProviderDubbingTranslationFailure(
            "provider_request", retryable=False, http_status=status, metadata=metadata
        )
    if status >= 500:
        return ProviderDubbingTranslationFailure(
            "provider_submission_ambiguous",
            retryable=False,
            ambiguous_submission=True,
            http_status=status,
            metadata=metadata,
        )
    return ProviderDubbingTranslationFailure(
        "provider_response", retryable=False, http_status=status, metadata=metadata
    )


def _normalize_text(value: str) -> str:
    normalized = "\n".join(
        line.rstrip() for line in value.replace("\r\n", "\n").split("\n")
    ).strip()
    if not 1 <= len(normalized) <= _MAX_SEGMENT_CHARACTERS or "\x00" in normalized:
        raise ProviderDubbingTranslationFailure(
            "provider_response", retryable=False
        )
    return normalized


def _validate_request(request: ProviderDubbingTranslationRequest) -> None:
    if request.provider != "openai" or request.model != _OPENAI_TRANSLATION_MODEL:
        raise ProviderDubbingTranslationFailure(
            "provider_operation_unsupported", retryable=False
        )
    if not 1 <= len(request.segments) <= _MAX_SEGMENTS:
        raise ProviderDubbingTranslationFailure("provider_input_invalid", retryable=False)
    if request.source_language == request.target_language:
        raise ProviderDubbingTranslationFailure("provider_input_invalid", retryable=False)
    if not request.source_language or not request.target_language:
        raise ProviderDubbingTranslationFailure("provider_input_invalid", retryable=False)
    if not 128 <= int(request.max_output_tokens) <= 16_384:
        raise ProviderDubbingTranslationFailure("provider_input_invalid", retryable=False)
    ids: set[str] = set()
    total = 0
    previous_end = 0
    for segment in request.segments:
        if not segment.segment_id or segment.segment_id in ids:
            raise ProviderDubbingTranslationFailure(
                "provider_input_invalid", retryable=False
            )
        if not segment.speaker_key.startswith("speaker-"):
            raise ProviderDubbingTranslationFailure(
                "provider_input_invalid", retryable=False
            )
        if not 0 <= segment.start_ms < segment.end_ms:
            raise ProviderDubbingTranslationFailure(
                "provider_input_invalid", retryable=False
            )
        if segment.start_ms < previous_end:
            raise ProviderDubbingTranslationFailure(
                "provider_input_invalid", retryable=False
            )
        text = _normalize_text(segment.text)
        total += len(text)
        previous_end = segment.end_ms
        ids.add(segment.segment_id)
    if total > _MAX_TOTAL_CHARACTERS:
        raise ProviderDubbingTranslationFailure("provider_input_invalid", retryable=False)


def _translation_schema(segment_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "translations": {
                "type": "array",
                "minItems": len(segment_ids),
                "maxItems": len(segment_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "segment_id": {"type": "string", "enum": list(segment_ids)},
                        "translated_text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": _MAX_SEGMENT_CHARACTERS,
                        },
                    },
                    "required": ["segment_id", "translated_text"],
                },
            }
        },
        "required": ["translations"],
    }


def _extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    pieces: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    pieces.append(text)
    return "".join(pieces)


class OpenAIDubbingTranslationAdapter:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        token = [REDACTED]
        if not token:
            [REDACTED] ProviderDubbingTranslationFailure(
                "provider_unconfigured", retryable=False
            )
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def invoke(
        self,
        request: ProviderDubbingTranslationRequest,
        *,
        credential: str,
        base_url: str,
    ) -> ProviderDubbingTranslationResult:
        _validate_request(request)
        segment_ids = tuple(item.segment_id for item in request.segments)
        source_payload = {
            "source_language": request.source_language,
            "target_language": request.target_language,
            "segments": [
                {
                    "segment_id": item.segment_id,
                    "speaker_key": item.speaker_key,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "text": item.text,
                }
                for item in request.segments
            ],
        }
        body = {
            "model": request.model,
            "store": False,
            "reasoning": {"effort": "none"},
            "instructions": (
                "Translate every segment faithfully into the requested target language. "
                "Preserve segment IDs exactly. Do not add explanations, speaker names, "
                "stage directions, markup, or omitted segments. Return only the schema."
            ),
            "input": json.dumps(
                source_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            "max_output_tokens": int(request.max_output_tokens),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "aionex_dubbing_translation",
                    "strict": True,
                    "schema": _translation_schema(segment_ids),
                }
            },
        }
        root = base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{root}/v1/responses",
                    headers=self._headers(credential),
                    json=body,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderDubbingTranslationFailure(
                "provider_submission_ambiguous",
                retryable=False,
                ambiguous_submission=True,
            ) from exc
        if response.status_code >= 400:
            raise _failure_for_response(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderDubbingTranslationFailure(
                "provider_response", retryable=False
            ) from exc
        if not isinstance(payload, dict) or payload.get("status") not in {
            None,
            "completed",
        }:
            raise ProviderDubbingTranslationFailure(
                "provider_response", retryable=False
            )
        output_text = _extract_output_text(payload)
        try:
            decoded = json.loads(output_text)
        except (TypeError, ValueError) as exc:
            raise ProviderDubbingTranslationFailure(
                "provider_response", retryable=False
            ) from exc
        items = decoded.get("translations") if isinstance(decoded, dict) else None
        if not isinstance(items, list):
            raise ProviderDubbingTranslationFailure(
                "provider_response", retryable=False
            )
        translations: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ProviderDubbingTranslationFailure(
                    "provider_response", retryable=False
                )
            segment_id = item.get("segment_id")
            translated_text = item.get("translated_text")
            if not isinstance(segment_id, str) or segment_id in translations:
                raise ProviderDubbingTranslationFailure(
                    "provider_response", retryable=False
                )
            if not isinstance(translated_text, str):
                raise ProviderDubbingTranslationFailure(
                    "provider_response", retryable=False
                )
            translations[segment_id] = _normalize_text(translated_text)
        if set(translations) != set(segment_ids):
            raise ProviderDubbingTranslationFailure(
                "provider_response", retryable=False
            )
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        actual_cost: float | None = None
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            actual_cost = round(
                input_tokens * _OPENAI_INPUT_USD_PER_MILLION / 1_000_000
                + output_tokens * _OPENAI_OUTPUT_USD_PER_MILLION / 1_000_000,
                9,
            )
        request_id = response.headers.get("x-request-id")
        if not request_id and isinstance(payload.get("id"), str):
            request_id = payload["id"]
        return ProviderDubbingTranslationResult(
            translations=translations,
            request_id=request_id,
            metadata={
                "model": request.model,
                "segment_count": len(segment_ids),
                "source_language": request.source_language,
                "target_language": request.target_language,
                "structured_output": True,
            },
            usage={
                "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
                "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
                "total_tokens": usage.get("total_tokens")
                if isinstance(usage.get("total_tokens"), int)
                else None,
                "actual_cost_known": actual_cost is not None,
                "input_usd_per_million_tokens": _OPENAI_INPUT_USD_PER_MILLION,
                "output_usd_per_million_tokens": _OPENAI_OUTPUT_USD_PER_MILLION,
            },
            actual_cost_usd=actual_cost,
            cost_basis=(
                "provider_usage_official_rates"
                if actual_cost is not None
                else "official_rate_cap"
            ),
        )


def default_dubbing_translation_adapters(
    *, timeout_seconds: float = 120.0,
) -> dict[str, OpenAIDubbingTranslationAdapter]:
    return {
        "openai": OpenAIDubbingTranslationAdapter(
            timeout_seconds=timeout_seconds
        )
    }
