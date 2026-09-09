"""Bounded Replicate transport for governed identity media.

The adapter never retries a prediction submission. File uploads and prediction
IDs are private runtime details and must not be returned to public clients.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx


class IdentityMediaProviderFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        ambiguous_submission: bool = False,
        http_status: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.ambiguous_submission = ambiguous_submission
        self.http_status = http_status




_PROVIDER_INPUT_DOMAIN = "aionex.identity-media.provider-input.v1"
_PROVIDER_INPUT_NAMES = frozenset({"image", "audio", "video"})


@dataclass(frozen=True, slots=True)
class ProviderInputGrant:
    execution_id: str
    input_name: str
    expires_at_epoch: int


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise IdentityMediaProviderFailure("provider_input_token_invalid") from exc


def _valid_execution_id(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 80 or any(ch not in "0123456789abcdefABCDEF-" for ch in text):
        raise IdentityMediaProviderFailure("provider_input_execution_invalid")
    return text


def issue_provider_input_token(
    *,
    execution_id: str,
    input_name: str,
    secret: str,
    ttl_seconds: int = 900,
    now_epoch: int | None = None,
) -> str:
    if len(str(secret or "")) < 32:
        raise IdentityMediaProviderFailure("provider_input_signing_secret_invalid")
    execution = _valid_execution_id(execution_id)
    name = str(input_name or "").strip().lower()
    if name not in _PROVIDER_INPUT_NAMES:
        raise IdentityMediaProviderFailure("provider_input_name_invalid")
    ttl = int(ttl_seconds)
    if not 60 <= ttl <= 1800:
        raise IdentityMediaProviderFailure("provider_input_ttl_invalid")
    current = int(time.time()) if now_epoch is None else int(now_epoch)
    payload = json.dumps(
        {"v": 1, "execution_id": execution, "input_name": name, "exp": current + ttl},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    encoded = _b64url(payload)
    signature = hmac.new(
        str(secret).encode("utf-8"),
        f"{_PROVIDER_INPUT_DOMAIN}|{encoded}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def verify_provider_input_token(
    token: str,
    *,
    secret: str,
    now_epoch: int | None = None,
) -> ProviderInputGrant:
    if len(str(secret or "")) < 32:
        raise IdentityMediaProviderFailure("provider_input_signing_secret_invalid")
    text = str(token or "").strip()
    if len(text) > 2048 or text.count(".") != 1:
        raise IdentityMediaProviderFailure("provider_input_token_invalid")
    encoded, supplied = text.split(".", 1)
    if len(supplied) != 64:
        raise IdentityMediaProviderFailure("provider_input_token_invalid")
    expected = hmac.new(
        str(secret).encode("utf-8"),
        f"{_PROVIDER_INPUT_DOMAIN}|{encoded}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise IdentityMediaProviderFailure("provider_input_token_invalid")
    try:
        payload = json.loads(_b64url_decode(encoded))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise IdentityMediaProviderFailure("provider_input_token_invalid") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise IdentityMediaProviderFailure("provider_input_token_invalid")
    try:
        execution = _valid_execution_id(str(payload["execution_id"]))
        name = str(payload["input_name"]).strip().lower()
        expiry = int(payload["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IdentityMediaProviderFailure("provider_input_token_invalid") from exc
    if name not in _PROVIDER_INPUT_NAMES:
        raise IdentityMediaProviderFailure("provider_input_token_invalid")
    current = int(time.time()) if now_epoch is None else int(now_epoch)
    if expiry < current or expiry > current + 1800:
        raise IdentityMediaProviderFailure("provider_input_token_expired")
    return ProviderInputGrant(execution, name, expiry)


def provider_input_url(origin: str, token: str, filename: str) -> str:
    value = str(origin or "").strip().rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.port not in {None, 443}
    ):
        raise IdentityMediaProviderFailure("provider_input_origin_invalid")
    name = str(filename or "").strip()
    if not name or len(name) > 160 or name != name.rsplit("/", 1)[-1] or name != name.rsplit("\\", 1)[-1]:
        raise IdentityMediaProviderFailure("provider_input_filename_invalid")
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in name):
        raise IdentityMediaProviderFailure("provider_input_filename_invalid")
    return (
        f"{value}/api/v1/studio/identity-media/provider-input/"
        f"{quote(str(token), safe='.')}/{quote(name, safe='._-')}"
    )


@dataclass(frozen=True, slots=True)
class ReplicateFile:
    file_id: str
    url: str


@dataclass(frozen=True, slots=True)
class ReplicatePrediction:
    prediction_id: str
    status: str
    output: Any
    error_present: bool
    metrics: dict[str, Any]


_MODEL_BY_OPERATION = {
    "voice_clone": "minimax/voice-cloning",
    "face_reenactment": "prunaai/p-video-avatar",
    "talking_head": "prunaai/p-video-avatar",
    "avatar_generation": "prunaai/p-video-avatar",
    "lip_sync": "sync/lipsync-2",
}


def model_for_operation(operation: str) -> str:
    try:
        return _MODEL_BY_OPERATION[operation]
    except KeyError as exc:
        raise IdentityMediaProviderFailure("identity_media_runtime_pending") from exc


def _safe_metrics(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("predict_time", "total_time"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            result[key] = float(value)
    return result


def _prediction(payload: Any) -> ReplicatePrediction:
    if not isinstance(payload, dict):
        raise IdentityMediaProviderFailure("provider_response_invalid")
    prediction_id = str(payload.get("id") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    if not prediction_id or status not in {"starting", "processing", "succeeded", "failed", "canceled"}:
        raise IdentityMediaProviderFailure("provider_response_invalid")
    return ReplicatePrediction(
        prediction_id=prediction_id,
        status=status,
        output=payload.get("output"),
        error_present=bool(payload.get("error")),
        metrics=_safe_metrics(payload.get("metrics")),
    )


def trusted_output_url(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "replicate.delivery" or host.endswith(".replicate.delivery")):
        raise IdentityMediaProviderFailure("provider_output_host_rejected")
    return raw


class ReplicateIdentityMediaAdapter:
    def __init__(
        self,
        credential: str,
        *,
        base_url: str = "https://api.replicate.com",
        timeout_seconds: float = 90.0,
        max_download_bytes: int = 268_435_456,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        token = str(credential or "").strip()
        if not token:
            raise IdentityMediaProviderFailure("provider_not_configured")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname != "api.replicate.com":
            raise IdentityMediaProviderFailure("provider_base_url_rejected")
        self.credential = token
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.credential}",
            "Accept": "application/json",
        }

    async def upload_private_file(
        self,
        *,
        body: bytes,
        filename: str,
        content_type: str,
    ) -> ReplicateFile:
        if not body or len(body) > 100 * 1024 * 1024:
            raise IdentityMediaProviderFailure("provider_file_size_rejected")
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/files",
                    headers=self._headers(),
                    files={"content": (filename, body, content_type)},
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise IdentityMediaProviderFailure("provider_file_upload_failed", retryable=True) from exc
        if response.status_code not in {200, 201}:
            raise IdentityMediaProviderFailure(
                "provider_file_upload_rejected",
                retryable=response.status_code in {429, 500, 502, 503, 504},
                http_status=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IdentityMediaProviderFailure("provider_response_invalid") from exc
        file_id = str(payload.get("id") or "").strip() if isinstance(payload, dict) else ""
        urls = payload.get("urls") if isinstance(payload, dict) else None
        url = ""
        if isinstance(urls, dict):
            url = str(urls.get("get") or "").strip()
        if not url and isinstance(payload, dict):
            url = str(payload.get("url") or "").strip()
        parsed = urlparse(url)
        if not file_id or parsed.scheme != "https" or not parsed.hostname:
            raise IdentityMediaProviderFailure("provider_file_response_invalid")
        return ReplicateFile(file_id=file_id, url=url)

    async def create_prediction(
        self,
        *,
        model: str,
        inputs: dict[str, Any],
        cancel_after_seconds: int = 600,
    ) -> ReplicatePrediction:
        if model not in set(_MODEL_BY_OPERATION.values()) | {"minimax/speech-02-hd"}:
            raise IdentityMediaProviderFailure("provider_model_rejected")
        owner, name = model.split("/", 1)
        headers = {
            **self._headers(),
            "Content-Type": "application/json",
            "Cancel-After": f"{max(60, min(int(cancel_after_seconds), 1800))}s",
        }
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/models/{owner}/{name}/predictions",
                    headers=headers,
                    json={"input": inputs},
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise IdentityMediaProviderFailure(
                    "provider_submission_ambiguous",
                    ambiguous_submission=True,
                ) from exc
        if response.status_code not in {200, 201}:
            ambiguous = response.status_code >= 500
            raise IdentityMediaProviderFailure(
                "provider_submission_ambiguous" if ambiguous else "provider_submission_rejected",
                ambiguous_submission=ambiguous,
                http_status=response.status_code,
            )
        try:
            return _prediction(response.json())
        except ValueError as exc:
            raise IdentityMediaProviderFailure("provider_response_invalid") from exc

    async def get_prediction(self, prediction_id: str) -> ReplicatePrediction:
        prediction = str(prediction_id or "").strip()
        if not prediction or len(prediction) > 200 or any(ch.isspace() for ch in prediction):
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
                raise IdentityMediaProviderFailure("provider_poll_failed", retryable=True) from exc
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
        url = trusted_output_url(value)
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=max(self.timeout_seconds, 180.0),
            follow_redirects=False,
        ) as client:
            try:
                response = await client.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise IdentityMediaProviderFailure("provider_download_failed", retryable=True) from exc
        if response.status_code != 200:
            raise IdentityMediaProviderFailure(
                "provider_download_rejected",
                retryable=response.status_code in {429, 500, 502, 503, 504},
                http_status=response.status_code,
            )
        body = response.content
        if not body or len(body) > self.max_download_bytes:
            raise IdentityMediaProviderFailure("provider_output_size_rejected")
        content_type = str(response.headers.get("content-type") or "application/octet-stream").split(";", 1)[0].strip().lower()
        return body, content_type
