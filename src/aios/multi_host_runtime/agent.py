from __future__ import annotations

import hashlib
import json
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .auth import HostRequestAuthenticator
from .client import MultiHostClientError, MultiHostControlClient


@dataclass(frozen=True, slots=True)
class MultiHostAgentConfig:
    cluster_id: str
    host_id: str
    service_url: str
    control_plane_url: str
    capabilities: tuple[str, ...]
    source_root: Path
    secret_file: Path
    ca_file: Path
    cert_file: Path
    key_file: Path
    heartbeat_interval: float = 1.0
    poll_interval: float = 0.1
    task_renew_interval: float = 0.75

    @classmethod
    def from_env(cls) -> "MultiHostAgentConfig":
        def required(name: str) -> str:
            value = os.environ.get(name, "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            return value

        capabilities = tuple(
            sorted(
                {
                    item.strip().lower()
                    for item in required("AIOS_MULTI_HOST_CAPABILITIES").split(",")
                    if item.strip()
                }
            )
        )
        config = cls(
            cluster_id=required("AIOS_MULTI_HOST_CLUSTER_ID"),
            host_id=required("AIOS_MULTI_HOST_HOST_ID"),
            service_url=required("AIOS_MULTI_HOST_SERVICE_URL"),
            control_plane_url=required("AIOS_MULTI_HOST_CONTROL_PLANE_URL"),
            capabilities=capabilities,
            source_root=Path(required("AIOS_MULTI_HOST_SOURCE_ROOT")),
            secret_file=Path(required("AIOS_MULTI_HOST_SECRET_FILE")),
            ca_file=Path(required("AIOS_MULTI_HOST_CA_FILE")),
            cert_file=Path(required("AIOS_MULTI_HOST_CERT_FILE")),
            key_file=Path(required("AIOS_MULTI_HOST_KEY_FILE")),
            heartbeat_interval=float(os.environ.get("AIOS_MULTI_HOST_HEARTBEAT_INTERVAL", "1")),
            poll_interval=float(os.environ.get("AIOS_MULTI_HOST_POLL_INTERVAL", "0.1")),
            task_renew_interval=float(os.environ.get("AIOS_MULTI_HOST_TASK_RENEW_INTERVAL", "0.75")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.service_url.startswith("https://"):
            raise ValueError("agent service_url must use HTTPS")
        if not self.control_plane_url.startswith("https://"):
            raise ValueError("control-plane URL must use HTTPS")
        if not self.capabilities:
            raise ValueError("at least one host capability is required")
        if not self.source_root.is_absolute() or not self.source_root.is_dir():
            raise ValueError("source root must be an existing absolute directory")
        if min(self.heartbeat_interval, self.poll_interval, self.task_renew_interval) <= 0:
            raise ValueError("agent timing values must be positive")
        for path in (self.secret_file, self.ca_file, self.cert_file, self.key_file):
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"agent credential file is missing or unsafe: {path}")


class MultiHostAgent:
    """Remote host agent using only the mutual-TLS control-plane API for shared state."""

    TASK_NAME = "phase24b.department"

    def __init__(self, config: MultiHostAgentConfig) -> None:
        self.config = config
        self.authenticator = HostRequestAuthenticator.from_file(
            config.host_id,
            config.secret_file,
        )
        self.client = MultiHostControlClient(
            config.control_plane_url,
            self.authenticator,
            config.ca_file,
            config.cert_file,
            config.key_file,
            timeout_seconds=2.0,
        )
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started_at = time.time()

    def _log(self, event: str, **details: Any) -> None:
        print(
            json.dumps(
                {
                    "event": event,
                    "host_id": self.config.host_id,
                    "time": round(time.time(), 6),
                    **details,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    def register(self) -> dict[str, Any]:
        response = self.client.request(
            "POST",
            "/v1/hosts/register",
            {
                "service_url": self.config.service_url,
                "capabilities": list(self.config.capabilities),
                "metadata": {
                    "runtime": "phase24b",
                    "pid": os.getpid(),
                },
            },
        )
        return response.payload

    def start(self) -> None:
        self.register()
        self._threads = [
            threading.Thread(target=self._heartbeat_loop, name=f"{self.config.host_id}-heartbeat", daemon=True),
            threading.Thread(target=self._work_loop, name=f"{self.config.host_id}-worker", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self._log("agent-started", control_plane=self.config.control_plane_url)

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._log("agent-stopped")

    def wait(self) -> None:
        while not self._stop.wait(0.5):
            pass

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.client.request("POST", "/v1/hosts/heartbeat", {})
                lease = self.client.request("POST", "/v1/leader/lease", {}).payload
                if lease.get("is_leader"):
                    self._log(
                        "leader-lease",
                        term=lease.get("term"),
                        expires_at=lease.get("expires_at"),
                    )
            except MultiHostClientError as exc:
                self._log("heartbeat-unreachable", error=type(exc).__name__)
            except BaseException as exc:
                self._log("heartbeat-error", error=type(exc).__name__)
            self._stop.wait(self.config.heartbeat_interval)

    def _work_loop(self) -> None:
        while not self._stop.is_set():
            try:
                response = self.client.request("POST", "/v1/tasks/claim", {})
                task = response.payload.get("task")
                if task is None:
                    self._stop.wait(self.config.poll_interval)
                    continue
                if not isinstance(task, dict):
                    raise RuntimeError("control-plane task response is invalid")
                self._execute_task(task)
            except MultiHostClientError:
                self._stop.wait(self.config.poll_interval)
            except BaseException as exc:
                self._log("worker-loop-error", error=type(exc).__name__)
                self._stop.wait(self.config.poll_interval)

    def _execute_task(self, task: dict[str, Any]) -> None:
        task_id = str(task.get("task_id") or "")
        task_name = str(task.get("name") or "")
        payload = task.get("payload")
        if not task_id or task_name != self.TASK_NAME or not isinstance(payload, dict):
            self._send_failure(task_id, "invalid or unsupported remote task")
            return

        renew_stop = threading.Event()
        renew_thread = threading.Thread(
            target=self._renew_loop,
            args=(task_id, renew_stop),
            name=f"{self.config.host_id}-renew-{task_id[:8]}",
            daemon=True,
        )
        renew_thread.start()
        try:
            result = self._department_result(task_id, payload)
        except BaseException as exc:
            self._send_failure(task_id, f"{type(exc).__name__}: {str(exc)[:700]}")
        else:
            try:
                self.client.request(
                    "POST",
                    "/v1/tasks/complete",
                    {"task_id": task_id, "result": result},
                )
                self._log(
                    "task-completed",
                    task_id=task_id,
                    department=result["department"],
                    attempts=task.get("attempts"),
                )
            except MultiHostClientError:
                self._log("task-completion-unreachable", task_id=task_id)
            except BaseException as exc:
                self._log(
                    "task-completion-rejected",
                    task_id=task_id,
                    error=type(exc).__name__,
                )
        finally:
            renew_stop.set()
            renew_thread.join(timeout=max(1.0, self.config.task_renew_interval * 2))

    def _renew_loop(self, task_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.config.task_renew_interval):
            try:
                self.client.request(
                    "POST",
                    "/v1/tasks/renew",
                    {"task_id": task_id},
                )
            except MultiHostClientError:
                self._log("task-renew-unreachable", task_id=task_id)
            except BaseException as exc:
                self._log(
                    "task-renew-rejected",
                    task_id=task_id,
                    error=type(exc).__name__,
                )
                return

    def _send_failure(self, task_id: str, error: str) -> None:
        if not task_id:
            return
        try:
            self.client.request(
                "POST",
                "/v1/tasks/fail",
                {"task_id": task_id, "error": error, "retry_delay_seconds": 0},
            )
        except BaseException:
            self._log("task-failure-unreachable", task_id=task_id)

    def _department_result(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        source_path = Path(str(payload.get("source_path") or ""))
        resolved_root = self.config.source_root.resolve(strict=True)
        resolved_source = source_path.resolve(strict=True)
        if resolved_root not in resolved_source.parents:
            raise ValueError("source evidence path escapes the configured source root")
        if not resolved_source.is_file() or resolved_source.is_symlink():
            raise ValueError("source evidence file is missing or unsafe")
        digest = hashlib.sha256(resolved_source.read_bytes()).hexdigest()
        expected = str(payload.get("source_sha256") or "").lower()
        if digest != expected:
            raise ValueError("source evidence hash mismatch")
        decoded = json.loads(resolved_source.read_text(encoding="utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("source evidence must be a JSON object")
        department = str(payload.get("department") or "")
        if decoded.get("department") != department:
            raise ValueError("source evidence department mismatch")
        criteria = payload.get("acceptance_criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError("task acceptance criteria are invalid")
        delay = max(0.0, min(float(payload.get("simulate_seconds") or 0.0), 60.0))
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if self._stop.wait(min(0.1, max(0.0, deadline - time.monotonic()))):
                raise RuntimeError("agent stopped during task execution")
        return {
            "schema_version": 1,
            "task_id": task_id,
            "host_id": self.config.host_id,
            "department": department,
            "source_path": str(resolved_source),
            "source_sha256": digest,
            "passed_criteria": [str(item) for item in criteria],
            "tests_passed": bool(decoded.get("tests_passed")),
            "security_reviewed": bool(decoded.get("security_reviewed")),
            "production_modified": False,
            "source_execution_modified": False,
        }


def main() -> int:
    config = MultiHostAgentConfig.from_env()
    agent = MultiHostAgent(config)

    def terminate(signum: int, frame: object) -> None:
        agent.stop()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    agent.start()
    agent.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
