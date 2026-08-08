from __future__ import annotations

from dataclasses import dataclass
import json
import time
import urllib.error
import urllib.request


class RunPodError(RuntimeError):
    """Sanitized RunPod lifecycle failure."""


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
            raise RunPodError(f"RunPod HTTP {exc.code}") from None
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
    """Minimal RunPod queue-endpoint client using the native Serverless v2 API."""

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
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            raise RunPodError(f"RunPod Serverless HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RunPodError(f"RunPod Serverless connection failed: {type(exc).__name__}") from None

    def health(self) -> dict:
        return self._request("GET", "/health", timeout=30)

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
        return self._request("GET", f"/status/{job_id}", timeout=30)
