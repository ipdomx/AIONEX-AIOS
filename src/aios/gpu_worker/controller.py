from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
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


@dataclass(frozen=True, slots=True)
class ServerlessCostGuardrails:
    max_queue_seconds: int = 300
    max_retries: int = 1
    estimated_gpu_cost_per_second_usd: float = 0.0
    max_estimated_job_cost_usd: float = 5.0
    daily_spend_limit_usd: float = 25.0
    monthly_spend_limit_usd: float = 500.0
    owner_alert_threshold_pct: int = 80

    def __post_init__(self) -> None:
        if not 10 <= self.max_queue_seconds <= 3600:
            raise ValueError("max_queue_seconds must be between 10 and 3600")
        if not 0 <= self.max_retries <= 3:
            raise ValueError("max_retries must be between 0 and 3")
        if self.estimated_gpu_cost_per_second_usd < 0:
            raise ValueError("estimated GPU cost must be non-negative")
        if min(self.max_estimated_job_cost_usd, self.daily_spend_limit_usd, self.monthly_spend_limit_usd) <= 0:
            raise ValueError("spend limits must be positive")
        if not 1 <= self.owner_alert_threshold_pct <= 100:
            raise ValueError("owner_alert_threshold_pct must be between 1 and 100")


class HunyuanServerlessController:
    """Run Hunyuan3D with queue recovery, bounded retries, and fail-closed spend guards."""

    def __init__(
        self,
        runpod,
        *,
        max_runtime_seconds: int = 1800,
        guardrails: ServerlessCostGuardrails | None = None,
        owner_alert: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        if not 60 <= max_runtime_seconds <= 14400:
            raise ValueError("max_runtime_seconds must be between 60 and 14400")
        self.runpod = runpod
        self.max_runtime_seconds = max_runtime_seconds
        self.guardrails = guardrails or ServerlessCostGuardrails()
        self.owner_alert = owner_alert

    def _alert(self, code: str, **details: object) -> None:
        if self.owner_alert is not None:
            self.owner_alert(code, details)

    def _enforce_spend(self, *, daily_spend_usd: float, monthly_spend_usd: float) -> None:
        estimated_job = self.guardrails.estimated_gpu_cost_per_second_usd * self.max_runtime_seconds
        if estimated_job > self.guardrails.max_estimated_job_cost_usd:
            self._alert("3d.cost.job_blocked", estimated_job_usd=estimated_job)
            raise RunPodError("Estimated GPU job cost exceeds owner limit")
        if daily_spend_usd + estimated_job > self.guardrails.daily_spend_limit_usd:
            self._alert("3d.cost.daily_blocked", daily_spend_usd=daily_spend_usd, estimated_job_usd=estimated_job)
            raise RunPodError("Daily GPU spend ceiling reached")
        if monthly_spend_usd + estimated_job > self.guardrails.monthly_spend_limit_usd:
            self._alert("3d.cost.monthly_blocked", monthly_spend_usd=monthly_spend_usd, estimated_job_usd=estimated_job)
            raise RunPodError("Monthly GPU spend ceiling reached")
        threshold = self.guardrails.owner_alert_threshold_pct / 100.0
        if daily_spend_usd + estimated_job >= self.guardrails.daily_spend_limit_usd * threshold:
            self._alert("3d.cost.daily_warning", daily_spend_usd=daily_spend_usd, estimated_job_usd=estimated_job)
        if monthly_spend_usd + estimated_job >= self.guardrails.monthly_spend_limit_usd * threshold:
            self._alert("3d.cost.monthly_warning", monthly_spend_usd=monthly_spend_usd, estimated_job_usd=estimated_job)

    def execute(
        self,
        payload: dict[str, object],
        *,
        artifact_path: Path | None = None,
        daily_spend_usd: float = 0.0,
        monthly_spend_usd: float = 0.0,
    ) -> GPUJobResult:
        self._enforce_spend(daily_spend_usd=daily_spend_usd, monthly_spend_usd=monthly_spend_usd)
        started = time.monotonic()
        last_error = "unknown"
        for attempt in range(self.guardrails.max_retries + 1):
            submitted = self.runpod.submit(payload, ttl_seconds=self.max_runtime_seconds + self.guardrails.max_queue_seconds)
            job_id = str(submitted.get("id") or "")
            if not job_id:
                raise RunPodError("RunPod Serverless job did not return an id")
            queue_started = time.monotonic()
            while True:
                elapsed = time.monotonic() - started
                status = self.runpod.status(job_id)
                state = str(status.get("status") or "")
                if state == "COMPLETED":
                    value = status.get("output")
                    if not isinstance(value, dict):
                        raise RunPodError("RunPod Serverless returned an invalid output")
                    output = value
                    encoded = output.get("content_base64")
                    if artifact_path is not None and isinstance(encoded, str):
                        artifact_path.parent.mkdir(parents=True, exist_ok=True)
                        artifact_path.write_bytes(base64.b64decode(encoded, validate=True))
                        output = {k: v for k, v in output.items() if k != "content_base64"}
                        output["artifact_path"] = str(artifact_path)
                    return GPUJobResult(True, output, round(elapsed, 3), True)
                if state in {"FAILED", "TIMED_OUT", "CANCELLED"}:
                    last_error = state.lower()
                    self._alert("3d.job.provider_failure", job_id=job_id, state=state, attempt=attempt + 1)
                    break
                if state == "IN_QUEUE" and time.monotonic() - queue_started > self.guardrails.max_queue_seconds:
                    self.runpod.cancel(job_id)
                    self.runpod.purge_queue()
                    last_error = "queue timeout"
                    self._alert("3d.job.stuck_recovered", job_id=job_id, attempt=attempt + 1)
                    break
                if elapsed > self.max_runtime_seconds:
                    self.runpod.cancel(job_id)
                    self.runpod.purge_queue()
                    self._alert("3d.job.runtime_blocked", job_id=job_id, elapsed_seconds=round(elapsed, 3))
                    raise RunPodError("RunPod Serverless runtime limit exceeded")
                time.sleep(5)
            if attempt >= self.guardrails.max_retries:
                raise RunPodError(f"RunPod Serverless job failed after recovery: {last_error}")
            self._alert("3d.job.retry", attempt=attempt + 2, previous_error=last_error)
        raise RunPodError("RunPod Serverless job failed")
