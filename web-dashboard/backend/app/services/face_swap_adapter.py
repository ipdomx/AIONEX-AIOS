"""Bounded Replicate transport for the FR-12 Face Swap contract.

This module is deliberately isolated from the shared identity-media worker until
FR-11 serializes the cross-scope endpoint/runtime integration.  It accepts only
execution-scoped signed HTTPS provider-input URLs, submits the pinned community
model version exactly once, and never turns the public model schema into runtime
approval.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.face_swap_contract import (
    FACE_SWAP_MODEL_VERSION,
    FACE_SWAP_PREDICTION_ENDPOINT,
)
from app.services.identity_media_replicate import (
    IdentityMediaProviderFailure,
    ReplicatePrediction,
    trusted_output_url,
)


_PROVIDER_INPUT_PATH_PREFIX = "/api/v1/studio/identity-media/provider-input/"
_ALLOWED_PREDICTION_STATES = frozenset(
    {"starting", "processing", "succeeded", "failed", "canceled"}
)


def _provider_input_url(value: str) -> str:
    """Accept only the existing private signed provider-input pull boundary."""

    raw = str(value or "").strip()
    if len(raw) > 4096:
        raise IdentityMediaProviderFailure("provider_input_url_invalid")
    parsed = urlparse(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(_PROVIDER_INPUT_PATH_PREFIX)
    ):
        raise IdentityMediaProviderFailure("provider_input_url_invalid")
    return raw


def _prediction(payload: Any) -> ReplicatePrediction:
    if not isinstance(payload, dict):
        raise IdentityMediaProviderFailure("provider_response_invalid")
    prediction_id = str(payload.get("id") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    if (
        not prediction_id
        or len(prediction_id) > 200
        or any(ch.isspace() for ch in prediction_id)
        or status not in _ALLOWED_PREDICTION_STATES
    ):
        raise IdentityMediaProviderFailure("provider_response_invalid")

    metrics: dict[str, Any] = {}
    raw_metrics = payload.get("metrics")
    if isinstance(raw_metrics, dict):
        for key in ("predict_time", "total_time"):
            value = raw_metrics.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                metrics[key] = float(value)

    return ReplicatePrediction(
        prediction_id=prediction_id,
        status=status,
        output=payload.get("output"),
        error_present=bool(payload.get("error")),
        metrics=metrics,
    )


def single_output_url(value: Any) -> str:
    """Return one trusted Replicate output URI and reject ambiguous envelopes."""

    candidate: Any
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, list) and len(value) == 1:
        candidate = value[0]
    else:
        raise IdentityMediaProviderFailure("provider_output_invalid")
    return trusted_output_url(candidate)


class FaceSwapReplicateAdapter:
    """Pinned-version Face Swap transport with no ambiguous resubmission."""

    def __init__(
        self,
        credential: str,
        *,
        base_url: str = "https://api.replicate.com",
        timeout_seconds: float = 90.0,
        max_download_bytes: int = 64 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        token = str(credential or "").strip()
        if not token:
            raise IdentityMediaProviderFailure("provider_not_configured")
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.replicate.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise IdentityMediaProviderFailure("provider_base_url_rejected")
        limit = int(max_download_bytes)
        if limit < 1024 or limit > 64 * 1024 * 1024:
            raise IdentityMediaProviderFailure("provider_output_limit_invalid")
        self.credential = token
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_download_bytes = limit
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.credential}",
            "Accept": "application/json",
        }

    async def submit(
        self,
        *,
        target_image_url: str,
        source_face_url: str,
        cancel_after_seconds: int = 600,
    ) -> ReplicatePrediction:
        """Submit once to /v1/predictions using the pinned community version."""

        target = _provider_input_url(target_image_url)
        source = _provider_input_url(source_face_url)
        cancel_after = max(60, min(int(cancel_after_seconds), 1800))
        headers = {
            **self._headers(),
            "Content-Type": "application/json",
            "Cancel-After": f"{cancel_after}s",
        }
        payload = {
            "version": FACE_SWAP_MODEL_VERSION,
            "input": {
                "input_image": target,
                "swap_image": source,
            },
        }

        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/predictions",
                    headers=headers,
                    json=payload,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # The provider may have accepted the request.  Never resubmit an
                # ambiguous Face Swap creation automatically.
                raise IdentityMediaProviderFailure(
                    "provider_submission_ambiguous",
                    ambiguous_submission=True,
                ) from exc

        if response.status_code not in {200, 201}:
            ambiguous = response.status_code >= 500
            raise IdentityMediaProviderFailure(
                "provider_submission_ambiguous"
                if ambiguous
                else "provider_submission_rejected",
                ambiguous_submission=ambiguous,
                http_status=response.status_code,
            )
        try:
            return _prediction(response.json())
        except ValueError as exc:
            raise IdentityMediaProviderFailure("provider_response_invalid") from exc

    async def get_prediction(self, prediction_id: str) -> ReplicatePrediction:
        prediction = str(prediction_id or "").strip()
        if (
            not prediction
            or len(prediction) > 200
            or any(ch.isspace() for ch in prediction)
            or "/" in prediction
        ):
            raise IdentityMediaProviderFailure("provider_prediction_id_invalid")

        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/v1/predictions/{prediction}",
                    headers=self._headers(),
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise IdentityMediaProviderFailure(
                    "provider_poll_failed",
                    retryable=True,
                ) from exc

        if response.status_code != 200:
            raise IdentityMediaProviderFailure(
                "provider_poll_rejected",
                retryable=response.status_code in {429, 500, 502, 503, 504},
                http_status=response.status_code,
            )
        try:
            return _prediction(response.json())
        except ValueError as exc:
            raise IdentityMediaProviderFailure("provider_response_invalid") from exc

    async def download_output(self, value: Any) -> tuple[bytes, str]:
        url = single_output_url(value)
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=max(self.timeout_seconds, 180.0),
            follow_redirects=False,
        ) as client:
            try:
                response = await client.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise IdentityMediaProviderFailure(
                    "provider_download_failed",
                    retryable=True,
                ) from exc

        if response.status_code != 200:
            raise IdentityMediaProviderFailure(
                "provider_download_rejected",
                retryable=response.status_code in {429, 500, 502, 503, 504},
                http_status=response.status_code,
            )
        body = response.content
        if not body or len(body) > self.max_download_bytes:
            raise IdentityMediaProviderFailure("provider_output_size_rejected")
        content_type = (
            str(response.headers.get("content-type") or "application/octet-stream")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        return body, content_type


assert FACE_SWAP_PREDICTION_ENDPOINT == "https://api.replicate.com/v1/predictions"
