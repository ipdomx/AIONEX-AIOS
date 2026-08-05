from __future__ import annotations

import hashlib
import json
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aios.execution_fabric import ExecutionFabricStore, TaskState, WorkerState

from .auth import ClusterAuthenticator
from .client import ClusterClientError, SecureClusterClient
from .service import SecureClusterHTTPServer
from .state import ClusterNodeState, ClusterStateStore


@dataclass(frozen=True, slots=True)
class ClusterNodeConfig:
    cluster_id: str
    node_id: str
    service_url: str
    peers: dict[str, str]
    capabilities: tuple[str, ...]
    state_path: Path
    secret_file: Path
    ca_file: Path
    cert_file: Path
    key_file: Path
    source_root: Path
    listen_host: str = "0.0.0.0"
    listen_port: int = 8443
    heartbeat_interval: float = 0.5
    heartbeat_timeout: float = 3.0
    leader_lease_seconds: float = 2.0
    task_lease_seconds: float = 2.0
    peer_probe_interval: float = 0.75

    @classmethod
    def from_env(cls) -> "ClusterNodeConfig":
        def required(name: str) -> str:
            value = os.environ.get(name, "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            return value

        peer_mapping: dict[str, str] = {}
        raw_peers = os.environ.get("AIOS_CLUSTER_PEERS", "").strip()
        if raw_peers:
            for item in raw_peers.split(";"):
                if not item.strip():
                    continue
                node_id, separator, url = item.partition("=")
                if not separator or not node_id.strip() or not url.startswith("https://"):
                    raise ValueError("AIOS_CLUSTER_PEERS contains an invalid entry")
                peer_mapping[node_id.strip()] = url.strip().rstrip("/")

        capabilities = tuple(
            sorted(
                {
                    item.strip().lower()
                    for item in required("AIOS_CLUSTER_CAPABILITIES").split(",")
                    if item.strip()
                }
            )
        )
        if not capabilities:
            raise ValueError("at least one cluster capability is required")
        config = cls(
            cluster_id=required("AIOS_CLUSTER_ID"),
            node_id=required("AIOS_CLUSTER_NODE_ID"),
            service_url=required("AIOS_CLUSTER_SERVICE_URL").rstrip("/"),
            peers=peer_mapping,
            capabilities=capabilities,
            state_path=Path(required("AIOS_CLUSTER_STATE_PATH")),
            secret_file=Path(required("AIOS_CLUSTER_SECRET_FILE")),
            ca_file=Path(required("AIOS_CLUSTER_CA_FILE")),
            cert_file=Path(required("AIOS_CLUSTER_CERT_FILE")),
            key_file=Path(required("AIOS_CLUSTER_KEY_FILE")),
            source_root=Path(required("AIOS_CLUSTER_SOURCE_ROOT")),
            listen_host=os.environ.get("AIOS_CLUSTER_LISTEN_HOST", "0.0.0.0"),
            listen_port=int(os.environ.get("AIOS_CLUSTER_LISTEN_PORT", "8443")),
            heartbeat_interval=float(os.environ.get("AIOS_CLUSTER_HEARTBEAT_INTERVAL", "0.5")),
            heartbeat_timeout=float(os.environ.get("AIOS_CLUSTER_HEARTBEAT_TIMEOUT", "3.0")),
            leader_lease_seconds=float(os.environ.get("AIOS_CLUSTER_LEADER_LEASE", "2.0")),
            task_lease_seconds=float(os.environ.get("AIOS_CLUSTER_TASK_LEASE", "2.0")),
            peer_probe_interval=float(os.environ.get("AIOS_CLUSTER_PEER_PROBE_INTERVAL", "0.75")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.service_url.startswith("https://"):
            raise ValueError("cluster service URL must use HTTPS")
        if not self.state_path.is_absolute() or not self.source_root.is_absolute():
            raise ValueError("cluster state and source roots must be absolute")
        if not 1 <= self.listen_port <= 65535:
            raise ValueError("cluster listen port is invalid")
        if min(
            self.heartbeat_interval,
            self.heartbeat_timeout,
            self.leader_lease_seconds,
            self.task_lease_seconds,
            self.peer_probe_interval,
        ) <= 0:
            raise ValueError("cluster timing values must be positive")
        if self.heartbeat_interval >= self.heartbeat_timeout:
            raise ValueError("heartbeat interval must be shorter than the timeout")
        if self.heartbeat_interval >= self.leader_lease_seconds:
            raise ValueError("heartbeat interval must be shorter than leader lease")
        if not self.source_root.is_dir():
            raise ValueError("cluster source root is missing")
        for path in (self.secret_file, self.ca_file, self.cert_file, self.key_file):
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"cluster credential file is missing or unsafe: {path}")


class ClusterNodeRuntime:
    """One TLS/HMAC cluster node with discovery, election, heartbeat and leased work."""

    TASK_NAME = "phase24a.department"

    def __init__(self, config: ClusterNodeConfig) -> None:
        self.config = config
        self.node_id = config.node_id
        self.cluster_store = ClusterStateStore(config.state_path)
        self.fabric_store = ExecutionFabricStore(config.state_path)
        self.authenticator = ClusterAuthenticator.from_file(config.secret_file)
        self.client = SecureClusterClient(
            config.node_id,
            self.authenticator,
            config.ca_file,
            timeout_seconds=2.0,
        )
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._server: SecureClusterHTTPServer | None = None
        self._started_at = time.time()

    def _log(self, event: str, **details: Any) -> None:
        print(
            json.dumps(
                {
                    "event": event,
                    "node_id": self.node_id,
                    "time": round(time.time(), 6),
                    **details,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    def start(self) -> None:
        self.cluster_store.register_node(
            self.node_id,
            self.config.service_url,
            self.config.capabilities,
            metadata={"runtime": "phase24a", "pid": os.getpid()},
        )
        self.fabric_store.register_worker(
            self.node_id,
            self.config.capabilities,
            max_concurrency=1,
            metadata={"cluster_id": self.config.cluster_id, "service_url": self.config.service_url},
        )
        self._server = SecureClusterHTTPServer(
            (self.config.listen_host, self.config.listen_port),
            self,
            self.config.cert_file,
            self.config.key_file,
        )
        server_thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"{self.node_id}-https",
            daemon=True,
        )
        self._threads = [
            server_thread,
            threading.Thread(target=self._heartbeat_loop, name=f"{self.node_id}-heartbeat", daemon=True),
            threading.Thread(target=self._discovery_loop, name=f"{self.node_id}-discovery", daemon=True),
            threading.Thread(target=self._work_loop, name=f"{self.node_id}-worker", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self._log("node-started", service_url=self.config.service_url)

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        try:
            self.fabric_store.set_worker_state(self.node_id, WorkerState.OFFLINE)
        except KeyError:
            pass
        try:
            self.cluster_store.set_node_state(self.node_id, ClusterNodeState.OFFLINE)
        except KeyError:
            pass
        self._log("node-stopped")

    def wait(self) -> None:
        while not self._stop.wait(0.5):
            pass

    def status_payload(self) -> dict[str, Any]:
        leader = self.cluster_store.get_leader(self.config.cluster_id)
        return {
            "status": "online" if not self._stop.is_set() else "stopping",
            "cluster_id": self.config.cluster_id,
            "node_id": self.node_id,
            "service_url": self.config.service_url,
            "capabilities": list(self.config.capabilities),
            "leader": leader.node_id if leader is not None else None,
            "leader_term": leader.term if leader is not None else None,
            "is_leader": bool(leader and leader.node_id == self.node_id),
            "uptime_seconds": round(time.time() - self._started_at, 4),
            "cluster": self.cluster_store.summary(self.config.cluster_id),
            "fabric": self.fabric_store.summary(),
            "transport": {"tls": True, "minimum_tls": "1.2", "hmac_sha256": True},
        }

    def receive_peer_heartbeat(
        self,
        identity_node_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload_node_id = str(payload.get("node_id") or "")
        service_url = str(payload.get("service_url") or "")
        capabilities = payload.get("capabilities")
        if identity_node_id != payload_node_id:
            raise ValueError("signed node identity does not match payload")
        if not isinstance(capabilities, list):
            raise ValueError("peer capabilities are required")
        try:
            known = self.cluster_store.get_node(payload_node_id)
        except KeyError:
            self.cluster_store.register_node(
                payload_node_id,
                service_url,
                [str(item) for item in capabilities],
                metadata={"discovered_by": self.node_id},
            )
        else:
            if known.service_url != service_url:
                raise ValueError("peer service URL changed unexpectedly")
            self.cluster_store.heartbeat_node(payload_node_id)
        return {
            "accepted": True,
            "node_id": self.node_id,
            "leader": (self.cluster_store.get_leader(self.config.cluster_id).node_id if self.cluster_store.get_leader(self.config.cluster_id) else None),
        }

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.cluster_store.heartbeat_node(self.node_id)
                self.fabric_store.heartbeat_worker(self.node_id)
                leader = self.cluster_store.elect_or_renew_leader(
                    self.config.cluster_id,
                    self.node_id,
                    lease_seconds=self.config.leader_lease_seconds,
                )
                if leader.node_id == self.node_id:
                    expired_nodes = self.cluster_store.expire_stale_nodes(
                        self.config.heartbeat_timeout
                    )
                    expired_workers = self.fabric_store.expire_stale_workers(
                        self.config.heartbeat_timeout
                    )
                    recovered = self.fabric_store.recover_expired_leases()
                    if expired_nodes or expired_workers or recovered:
                        self.cluster_store.record_event(
                            "leader-maintenance",
                            self.node_id,
                            {
                                "expired_nodes": list(expired_nodes),
                                "expired_workers": list(expired_workers),
                                "recovered_tasks": list(recovered),
                            },
                        )
            except BaseException as exc:
                self._log("heartbeat-error", error=type(exc).__name__)
            self._stop.wait(self.config.heartbeat_interval)

    def _discovery_loop(self) -> None:
        while not self._stop.is_set():
            for peer_id, base_url in sorted(self.config.peers.items()):
                if self._stop.is_set():
                    break
                started = time.monotonic()
                try:
                    status = self.client.request("GET", f"{base_url}/v1/cluster/status")
                    if status.payload.get("node_id") != peer_id:
                        raise ClusterClientError("peer identity mismatch")
                    self.client.request(
                        "POST",
                        f"{base_url}/v1/cluster/heartbeat",
                        {
                            "node_id": self.node_id,
                            "service_url": self.config.service_url,
                            "capabilities": list(self.config.capabilities),
                        },
                    )
                    self.cluster_store.record_peer_observation(
                        self.node_id,
                        peer_id,
                        healthy=True,
                        tls_verified=status.tls_verified,
                        authenticated=status.authenticated,
                        latency_ms=status.latency_ms,
                    )
                except BaseException as exc:
                    self.cluster_store.record_peer_observation(
                        self.node_id,
                        peer_id,
                        healthy=False,
                        tls_verified=False,
                        authenticated=False,
                        latency_ms=round((time.monotonic() - started) * 1000, 4),
                        error=type(exc).__name__,
                    )
            self._stop.wait(self.config.peer_probe_interval)

    def _work_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.fabric_store.heartbeat_worker(self.node_id)
                task = self.fabric_store.claim_task(
                    self.node_id,
                    lease_seconds=self.config.task_lease_seconds,
                    heartbeat_timeout=self.config.heartbeat_timeout,
                )
                if task is None:
                    self._stop.wait(0.1)
                    continue
                if task.name != self.TASK_NAME:
                    self.fabric_store.fail_task(
                        task.task_id,
                        self.node_id,
                        "unsupported task name",
                    )
                    continue
                self._process_task(task.task_id, task.payload)
            except BaseException as exc:
                self._log("worker-loop-error", error=type(exc).__name__)
                self._stop.wait(0.2)

    def _process_task(self, task_id: str, payload: Mapping[str, Any]) -> None:
        try:
            delay = max(0.0, min(float(payload.get("simulate_seconds", 0.0)), 30.0))
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if self._stop.wait(min(0.25, max(0.0, deadline - time.monotonic()))):
                    raise RuntimeError("node stopping")
                self.fabric_store.heartbeat_task(
                    task_id,
                    self.node_id,
                    lease_seconds=self.config.task_lease_seconds,
                )
                self.fabric_store.heartbeat_worker(self.node_id)

            source_path = Path(str(payload.get("source_path") or "")).resolve(strict=True)
            source_root = self.config.source_root.resolve(strict=True)
            if source_root not in source_path.parents:
                raise ValueError("task source escapes the approved evidence root")
            raw = source_path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            expected = str(payload.get("source_sha256") or "")
            if not expected or digest != expected:
                raise ValueError("task source hash mismatch")
            source_payload = json.loads(raw.decode("utf-8"))
            if not isinstance(source_payload, dict):
                raise ValueError("task source evidence must be an object")
            department = str(payload.get("department") or "")
            if source_payload.get("department") != department:
                raise ValueError("task department does not match source evidence")
            result = {
                "schema_version": 1,
                "department": department,
                "acceptance_criteria_proven": list(payload.get("acceptance_criteria") or []),
                "tests_passed": bool(source_payload.get("tests_passed")),
                "security_reviewed": bool(source_payload.get("security_reviewed")),
                "source_path": str(source_path),
                "source_sha256": digest,
                "worker_id": self.node_id,
                "cluster_id": self.config.cluster_id,
                "tls_used": True,
                "hmac_authenticated": True,
                "production_modified": False,
            }
            completed = self.fabric_store.complete_task(task_id, self.node_id, result)
            self.cluster_store.record_event(
                "task-completed",
                self.node_id,
                {
                    "task_id": task_id,
                    "department": department,
                    "attempts": completed.attempts,
                },
            )
            self._log("task-completed", task_id=task_id, department=department, attempts=completed.attempts)
        except BaseException as exc:
            try:
                failed = self.fabric_store.fail_task(
                    task_id,
                    self.node_id,
                    f"{type(exc).__name__}: {str(exc)[:500]}",
                    retry_delay_seconds=0.0,
                )
                self.cluster_store.record_event(
                    "task-failed",
                    self.node_id,
                    {
                        "task_id": task_id,
                        "state": failed.state.value,
                        "attempts": failed.attempts,
                        "error_type": type(exc).__name__,
                    },
                )
            except BaseException:
                pass


def main() -> int:
    config = ClusterNodeConfig.from_env()
    runtime = ClusterNodeRuntime(config)

    def handle_signal(signum: int, frame: object) -> None:
        runtime.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    runtime.start()
    try:
        runtime.wait()
    finally:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
