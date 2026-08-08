from __future__ import annotations

from dataclasses import dataclass
import base64
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from .runpod import RunPodClient, RunPodError


@dataclass(frozen=True, slots=True)
class GPUJobResult:
    success: bool
    output: dict[str, object]
    elapsed_seconds: float
    stopped_after_run: bool


class HunyuanGPUWorkerController:
    """Start-on-demand Hunyuan3D orchestration with fail-closed cost boundaries."""

    def __init__(
        self,
        runpod: RunPodClient,
        *,
        pod_id: str,
        api_url: str,
        worker_token: str = "",
        max_runtime_seconds: int = 3600,
        stop_after_run: bool = True,
    ) -> None:
        if not pod_id.strip() or not api_url.startswith("https://"):
            raise ValueError("pod_id and HTTPS api_url are required")
        if not worker_token.strip():
            raise ValueError("worker_token is required")
        if not 60 <= max_runtime_seconds <= 14400:
            raise ValueError("max_runtime_seconds must be between 60 and 14400")
        self.runpod = runpod
        self.pod_id = pod_id.strip()
        self.api_url = api_url.rstrip("/")
        self.worker_token = worker_token.strip()
        self.max_runtime_seconds = max_runtime_seconds
        self.stop_after_run = stop_after_run

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.worker_token}"}

    def health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.api_url}/health", headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            return False

    def execute(self, payload: dict[str, object], *, artifact_path: Path | None = None) -> GPUJobResult:
        started = time.monotonic()
        stopped = False
        self.runpod.start(self.pod_id)
        self.runpod.wait_running(self.pod_id, timeout_seconds=min(self.max_runtime_seconds, 900))
        deadline = time.monotonic() + min(self.max_runtime_seconds, 1200)
        while time.monotonic() < deadline and not self.health():
            time.sleep(5)
        if not self.health():
            if self.stop_after_run:
                self.runpod.stop(self.pod_id)
                stopped = True
            raise RunPodError("Hunyuan worker API did not become healthy")
        try:
            headers = {**self._headers(), "Content-Type": "application/json"}
            req = urllib.request.Request(
                f"{self.api_url}/generate",
                data=json.dumps(payload).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.max_runtime_seconds) as response:
                output = json.loads(response.read().decode())
            encoded = output.get("content_base64")
            if artifact_path is not None and isinstance(encoded, str):
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_path.write_bytes(base64.b64decode(encoded, validate=True))
                output = {k: v for k, v in output.items() if k != "content_base64"}
                output["artifact_path"] = str(artifact_path)
            return GPUJobResult(True, output, round(time.monotonic() - started, 3), False)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
            raise RunPodError(f"Hunyuan worker request failed: {type(exc).__name__}") from None
        finally:
            if self.stop_after_run:
                try:
                    self.runpod.stop(self.pod_id)
                    stopped = True
                except (RunPodError, OSError):
                    stopped = False


class HunyuanServerlessController:
    """Run Hunyuan3D on RunPod Serverless (scale-to-zero, pay only while running)."""

    def __init__(self, runpod, *, max_runtime_seconds: int = 3600) -> None:
        if not 60 <= max_runtime_seconds <= 14400:
            raise ValueError("max_runtime_seconds must be between 60 and 14400")
        self.runpod = runpod
        self.max_runtime_seconds = max_runtime_seconds

    def execute(self, payload: dict[str, object], *, artifact_path: Path | None = None) -> GPUJobResult:
        started = time.monotonic()
        wait_ms = min(self.max_runtime_seconds * 1000, 300000)
        output = self.runpod.run_sync(payload, wait_ms=wait_ms)
        if "job_id" in output:
            job_id = str(output["job_id"])
            deadline = time.monotonic() + self.max_runtime_seconds
            while time.monotonic() < deadline:
                status = self.runpod.status(job_id)
                state = str(status.get("status") or "")
                if state == "COMPLETED":
                    value = status.get("output")
                    if not isinstance(value, dict):
                        raise RunPodError("RunPod Serverless returned an invalid output")
                    output = value
                    break
                if state in {"FAILED", "TIMED_OUT", "CANCELLED"}:
                    raise RunPodError(f"RunPod Serverless job {state.lower()}")
                time.sleep(5)
            else:
                raise RunPodError("Timed out waiting for RunPod Serverless job")
        encoded = output.get("content_base64")
        if artifact_path is not None and isinstance(encoded, str):
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(base64.b64decode(encoded, validate=True))
            output = {k: v for k, v in output.items() if k != "content_base64"}
            output["artifact_path"] = str(artifact_path)
        return GPUJobResult(True, output, round(time.monotonic() - started, 3), True)
