from __future__ import annotations

from dataclasses import dataclass
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
    """Start-on-demand GPU orchestration with a fail-closed spend/time boundary."""

    def __init__(
        self,
        runpod: RunPodClient,
        *,
        pod_id: str,
        api_url: str,
        max_runtime_seconds: int = 3600,
        stop_after_run: bool = True,
    ) -> None:
        if not pod_id.strip() or not api_url.startswith("https://"):
            raise ValueError("pod_id and HTTPS api_url are required")
        if not 60 <= max_runtime_seconds <= 14400:
            raise ValueError("max_runtime_seconds must be between 60 and 14400")
        self.runpod = runpod
        self.pod_id = pod_id.strip()
        self.api_url = api_url.rstrip("/")
        self.max_runtime_seconds = max_runtime_seconds
        self.stop_after_run = stop_after_run

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.api_url}/health", timeout=15) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    def execute(self, payload: dict[str, object]) -> GPUJobResult:
        started = time.monotonic()
        stopped = False
        self.runpod.start(self.pod_id)
        self.runpod.wait_running(self.pod_id, timeout_seconds=min(self.max_runtime_seconds, 900))
        deadline = time.monotonic() + min(self.max_runtime_seconds, 900)
        while time.monotonic() < deadline and not self.health():
            time.sleep(5)
        if not self.health():
            if self.stop_after_run:
                self.runpod.stop(self.pod_id)
                stopped = True
            raise RunPodError("Hunyuan worker API did not become healthy")
        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.api_url}/generate",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.max_runtime_seconds) as response:
                output = json.loads(response.read().decode())
            return GPUJobResult(True, output, round(time.monotonic() - started, 3), False)
        finally:
            if self.stop_after_run:
                try:
                    self.runpod.stop(self.pod_id)
                    stopped = True
                except Exception:
                    stopped = False
