from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
import urllib.error
import urllib.request

# Provider error codes that no retry can fix: the endpoint was paused by the
# operator (max_workers=0) or the credential is not accepted.
PAUSED_ERROR_CODES = frozenset({"ENDPOINT_PAUSED"})
AUTH_HTTP_STATUSES = frozenset({401, 403})
_MAX_ERROR_BODY_BYTES = 4096
_MAX_PROVIDER_MESSAGE_CHARS = 160
_PAUSED_MESSAGE = re.compile(r"\bendpoint\s+is\s+paused\b", re.IGNORECASE)
_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"(?i)\brpa_[A-Za-z0-9]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+"),
    re.compile(r"[A-Za-z0-9+/_=-]{32,}"),
)


def sanitize_provider_text(value: object, *, limit: int = _MAX_PROVIDER_MESSAGE_CHARS) -> str | None:
    """Return a short, log-safe provider message with credentials redacted."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(value or ""))
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = " ".join(text.split())
    if not text:
        return None
    return text[:limit]


def sanitize_provider_code(value: object) -> str | None:
    code = re.sub(r"[^A-Z0-9_]", "_", str(value or "").strip().upper())[:64].strip("_")
    return code or None


def _error_fields(raw: bytes) -> tuple[str | None, str | None]:
    """Extract (code, message) from a RunPod error body without trusting it."""
    try:
        document = json.loads(raw.decode("utf-8", "replace")) if raw else None
    except json.JSONDecodeError:
        return None, sanitize_provider_text(raw.decode("utf-8", "replace")) if raw else None
    code: object = None
    message: object = None
    if isinstance(document, dict):
        nested = document.get("error")
        if isinstance(nested, dict):
            code = nested.get("code") or nested.get("error_code")
            message = nested.get("message") or nested.get("error")
        else:
            message = nested if isinstance(nested, str) else document.get("message")
        code = code or document.get("code") or document.get("error_code") or document.get("errorCode")
    elif isinstance(document, str):
        message = document
    clean_code = sanitize_provider_code(code) if isinstance(code, (str, int)) else None
    clean_message = sanitize_provider_text(message) if isinstance(message, str) else None
    if clean_code is None and clean_message and _PAUSED_MESSAGE.search(clean_message):
        clean_code = "ENDPOINT_PAUSED"
    return clean_code, clean_message


class RunPodError(RuntimeError):
    """Sanitized RunPod lifecycle failure.

    ``status``, ``code`` and ``provider_message`` carry the HTTP status and the
    sanitized provider error so callers can log them and classify the failure
    without ever seeing credentials.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.provider_message = provider_message

    @classmethod
    def from_http(cls, prefix: str, status: int, raw: bytes) -> RunPodError:
        code, provider_message = _error_fields(raw)
        text = f"{prefix} HTTP {status}"
        if code:
            text += f" {code}"
        if provider_message:
            text += f": {provider_message}"
        return cls(text, status=status, code=code, provider_message=provider_message)

    @property
    def category(self) -> str:
        """``paused``, ``auth`` or ``transient``."""
        if self.code in PAUSED_ERROR_CODES:
            return "paused"
        if self.status in AUTH_HTTP_STATUSES:
            return "auth"
        return "transient"

    @property
    def permanent(self) -> bool:
        """True when retrying the same request cannot succeed."""
        return self.category != "transient"

    def safe_details(self) -> dict[str, object]:
        return {
            "http_status": self.status,
            "provider_error_code": self.code,
            "provider_error_message": self.provider_message,
            "error_category": self.category,
        }


def _read_error_body(exc: urllib.error.HTTPError) -> bytes:
    try:
        return exc.read(_MAX_ERROR_BODY_BYTES) or b""
    except (OSError, ValueError):
        return b""


@dataclass(frozen=True, slots=True)
class RunPodPod:
    pod_id: str
    desired_status: str | None = None
    runtime_status: str | None = None
    public_ip: str | None = None
    cost_per_hour: float | None = None


class RunPodClient:
    """RunPod REST client for an on-demand, pre-provisioned GPU Pod.

    REST is intentionally used instead of the legacy GraphQL API so scoped
    RunPod API keys can be used with least privilege.
    """

    def __init__(self, api_key: str, endpoint: str = "https://rest.runpod.io/v1") -> None:
        if not api_key.strip():
            raise ValueError("RunPod API key is required")
        if not endpoint.startswith("https://"):
            raise ValueError("RunPod endpoint must use HTTPS")
        self.api_key = api_key.strip()
        self.endpoint = endpoint.rstrip("/")

    def _request(self, method: str, path: str, body: dict[str, object] | None = None) -> dict:
        payload = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                raw = response.read()
                return json.loads(raw.decode()) if raw else {}
        except urllib.error.HTTPError as exc:
            raise RunPodError.from_http("RunPod", exc.code, _read_error_body(exc)) from None
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RunPodError(f"RunPod connection failed: {type(exc).__name__}") from None

    @staticmethod
    def _pod_from_json(data: dict[str, object]) -> RunPodPod:
        status = str(data.get("desiredStatus") or "").upper() or None
        return RunPodPod(
            pod_id=str(data.get("id") or ""),
            desired_status=status,
            runtime_status="running" if status == "RUNNING" else "stopped",
            public_ip=str(data.get("publicIp") or "") or None,
            cost_per_hour=float(data["costPerHr"]) if data.get("costPerHr") is not None else None,
        )

    def get_pod(self, pod_id: str) -> RunPodPod:
        data = self._request("GET", f"/pods/{pod_id}")
        if not data.get("id"):
            raise RunPodError("RunPod pod not found")
        return self._pod_from_json(data)

    def start(self, pod_id: str) -> RunPodPod:
        data = self._request("POST", f"/pods/{pod_id}/start")
        return self._pod_from_json(data) if data.get("id") else self.get_pod(pod_id)

    def stop(self, pod_id: str) -> RunPodPod:
        data = self._request("POST", f"/pods/{pod_id}/stop")
        return self._pod_from_json(data) if data.get("id") else self.get_pod(pod_id)

    def wait_running(self, pod_id: str, timeout_seconds: float = 600, poll_seconds: float = 5) -> RunPodPod:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            pod = self.get_pod(pod_id)
            if pod.runtime_status == "running":
                return pod
            time.sleep(poll_seconds)
        raise RunPodError("Timed out waiting for GPU pod to start")


class RunPodServerlessClient:
    """RunPod Serverless v2 client with explicit recovery primitives."""

    def __init__(self, api_key: str, endpoint_id: str) -> None:
        if not api_key.strip() or not endpoint_id.strip():
            raise ValueError("RunPod API key and endpoint_id are required")
        self.api_key = api_key.strip()
        self.endpoint_id = endpoint_id.strip()
        self.base_url = f"https://api.runpod.ai/v2/{self.endpoint_id}"

    def _request(self, method: str, path: str, body: dict[str, object] | None = None, timeout: float = 60) -> dict:
        payload = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw.decode()) if raw else {}
        except urllib.error.HTTPError as exc:
            raise RunPodError.from_http(
                "RunPod Serverless", exc.code, _read_error_body(exc)
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RunPodError(f"RunPod Serverless connection failed: {type(exc).__name__}") from None

    def health(self) -> dict:
        return self._request("GET", "/health", timeout=30)

    def submit(self, payload: dict[str, object], *, ttl_seconds: int | None = None) -> dict:
        body: dict[str, object] = {"input": payload}
        if ttl_seconds is not None:
            body["policy"] = {"ttl": max(10, int(ttl_seconds)) * 1000}
        result = self._request("POST", "/run", body, timeout=90)
        job_id = result.get("id")
        if not job_id:
            raise RunPodError("RunPod Serverless job did not return an id")
        return result

    def run_sync(self, payload: dict[str, object], *, wait_ms: int = 300000) -> dict:
        wait_ms = max(1000, min(int(wait_ms), 300000))
        result = self._request("POST", f"/runsync?wait={wait_ms}", {"input": payload}, timeout=(wait_ms / 1000) + 30)
        status = str(result.get("status") or "")
        if status == "COMPLETED":
            output = result.get("output")
            if not isinstance(output, dict):
                raise RunPodError("RunPod Serverless returned an invalid output")
            return output
        if status in {"FAILED", "TIMED_OUT", "CANCELLED"}:
            raise RunPodError(f"RunPod Serverless job {status.lower()}")
        job_id = result.get("id")
        if not job_id:
            raise RunPodError("RunPod Serverless job did not return an id")
        return {"job_id": str(job_id), "status": status or "IN_QUEUE"}

    def status(self, job_id: str) -> dict:
        if not job_id.strip():
            raise ValueError("job_id is required")
        return self._request("GET", f"/status/{job_id.strip()}", timeout=30)

    def cancel(self, job_id: str) -> dict:
        if not job_id.strip():
            raise ValueError("job_id is required")
        return self._request("POST", f"/cancel/{job_id.strip()}", timeout=30)

    def purge_queue(self) -> dict:
        return self._request("POST", "/purge-queue", timeout=30)
