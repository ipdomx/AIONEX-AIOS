from __future__ import annotations

import json
import os
import re
import signal
import sqlite3
import ssl
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

from .auth import (
    HOST_HEADER,
    HostRequestAuthenticator,
    MultiHostAuthenticationError,
    certificate_sha256,
)
from .models import HostRecord, HostState
from .store import MultiHostControlStore


_HOST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class HostSecretRegistry:
    """Loads one external HMAC key per enrolled host without returning key material."""

    def __init__(self, directory: str | Path) -> None:
        root = Path(directory)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("host secret directory is missing or unsafe")
        self.directory = root
        self._cache: dict[str, HostRequestAuthenticator] = {}
        self._lock = threading.Lock()

    def authenticator(self, host_id: str) -> HostRequestAuthenticator:
        if not _HOST_ID.fullmatch(host_id):
            raise MultiHostAuthenticationError("host identity is invalid")
        with self._lock:
            cached = self._cache.get(host_id)
            if cached is not None:
                return cached
            path = self.directory / f"{host_id}.key"
            try:
                authenticator = HostRequestAuthenticator.from_file(host_id, path)
            except ValueError as exc:
                raise MultiHostAuthenticationError("host secret is unavailable") from exc
            self._cache[host_id] = authenticator
            return authenticator

    def __repr__(self) -> str:
        return f"HostSecretRegistry(directory={str(self.directory)!r}, secrets='[REDACTED]')"


class MultiHostControlPlane:
    """Mutual-TLS state authority for hosts, leases, leader fencing, and task recovery."""

    def __init__(
        self,
        state_path: str | Path,
        cluster_id: str,
        host_secret_directory: str | Path,
        *,
        heartbeat_timeout: float = 10.0,
        leader_lease_seconds: float = 5.0,
        task_lease_seconds: float = 5.0,
    ) -> None:
        if not cluster_id.strip():
            raise ValueError("cluster_id is required")
        if min(heartbeat_timeout, leader_lease_seconds, task_lease_seconds) <= 0:
            raise ValueError("control-plane timing values must be positive")
        self.cluster_id = cluster_id
        self.store = MultiHostControlStore(state_path)
        self.secrets = HostSecretRegistry(host_secret_directory)
        self.heartbeat_timeout = float(heartbeat_timeout)
        self.leader_lease_seconds = float(leader_lease_seconds)
        self.task_lease_seconds = float(task_lease_seconds)
        self.started_at = time.time()

    def load_enrollment_manifest(self, path: str | Path) -> tuple[HostRecord, ...]:
        manifest_path = Path(path)
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("enrollment manifest is missing or unsafe")
        try:
            decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("enrollment manifest is invalid") from exc
        if not isinstance(decoded, dict) or decoded.get("cluster_id") != self.cluster_id:
            raise ValueError("enrollment manifest cluster does not match")
        hosts = decoded.get("hosts")
        if not isinstance(hosts, list) or not hosts:
            raise ValueError("enrollment manifest contains no hosts")
        records: list[HostRecord] = []
        seen: set[str] = set()
        for item in hosts:
            if not isinstance(item, Mapping):
                raise ValueError("enrollment host entry is invalid")
            host_id = str(item.get("host_id") or "")
            if not _HOST_ID.fullmatch(host_id) or host_id in seen:
                raise ValueError("enrollment host identity is invalid or duplicated")
            capabilities = item.get("capabilities")
            if not isinstance(capabilities, list):
                raise ValueError("enrollment host capabilities are invalid")
            record = self.store.enroll_host(
                host_id,
                str(item.get("service_url") or ""),
                [str(value) for value in capabilities],
                str(item.get("certificate_sha256") or ""),
                metadata={
                    "deployment_host": str(item.get("deployment_host") or ""),
                    "enrollment_manifest": str(manifest_path),
                },
            )
            self.secrets.authenticator(host_id)
            records.append(record)
            seen.add(host_id)
        return tuple(records)

    @staticmethod
    def host_payload(host: HostRecord) -> dict[str, Any]:
        return {
            "host_id": host.host_id,
            "service_url": host.service_url,
            "capabilities": list(host.capabilities),
            "certificate_sha256": host.certificate_sha256,
            "state": host.state.value,
            "heartbeat_at": host.heartbeat_at,
            "enrolled_at": host.enrolled_at,
            "metadata": host.metadata,
        }

    @staticmethod
    def task_payload(task: Any) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "execution_id": task.execution_id,
            "name": task.name,
            "capability": task.capability,
            "payload": task.payload,
            "priority": task.priority,
            "state": task.state.value,
            "attempts": task.attempts,
            "max_attempts": task.max_attempts,
            "available_at": task.available_at,
            "lease_owner": task.lease_owner,
            "lease_expires_at": task.lease_expires_at,
            "result": task.result,
            "error": task.error,
            "idempotency_key": task.idempotency_key,
        }

    def register_host(
        self,
        host_id: str,
        peer_fingerprint: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        capabilities = payload.get("capabilities")
        if not isinstance(capabilities, list):
            raise ValueError("host capabilities are required")
        metadata = payload.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValueError("host metadata must be an object")
        host = self.store.register_host(
            host_id,
            peer_fingerprint,
            service_url=str(payload.get("service_url") or ""),
            capabilities=[str(item) for item in capabilities],
            metadata=dict(metadata or {}),
        )
        return {
            "accepted": True,
            "host": self.host_payload(host),
            "cluster_id": self.cluster_id,
        }

    def heartbeat_host(self, host_id: str, peer_fingerprint: str) -> dict[str, Any]:
        host = self.store.heartbeat_host(host_id, peer_fingerprint)
        leader = self.store.get_leader(self.cluster_id)
        return {
            "accepted": True,
            "host": self.host_payload(host),
            "leader": leader.host_id if leader else None,
            "leader_term": leader.term if leader else None,
        }

    def leader_lease(self, host_id: str, peer_fingerprint: str) -> dict[str, Any]:
        self.store.heartbeat_host(host_id, peer_fingerprint)
        lease = self.store.elect_or_renew_leader(
            self.cluster_id,
            host_id,
            lease_seconds=self.leader_lease_seconds,
        )
        return {
            "cluster_id": lease.cluster_id,
            "host_id": lease.host_id,
            "term": lease.term,
            "fencing_token": lease.fencing_token,
            "acquired_at": lease.acquired_at,
            "expires_at": lease.expires_at,
            "is_leader": lease.host_id == host_id,
        }

    def claim_task(self, host_id: str, peer_fingerprint: str) -> dict[str, Any]:
        self.store.heartbeat_host(host_id, peer_fingerprint)
        self.store.maintenance(self.heartbeat_timeout)
        task = self.store.fabric.claim_task(
            host_id,
            lease_seconds=self.task_lease_seconds,
            heartbeat_timeout=self.heartbeat_timeout,
        )
        return {
            "task": self.task_payload(task) if task is not None else None,
        }

    def renew_task(
        self,
        host_id: str,
        peer_fingerprint: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.store.heartbeat_host(host_id, peer_fingerprint)
        task = self.store.fabric.heartbeat_task(
            str(payload.get("task_id") or ""),
            host_id,
            lease_seconds=self.task_lease_seconds,
        )
        return {"task": self.task_payload(task)}

    def complete_task(
        self,
        host_id: str,
        peer_fingerprint: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.store.heartbeat_host(host_id, peer_fingerprint)
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise ValueError("task result must be an object")
        task = self.store.fabric.complete_task(
            str(payload.get("task_id") or ""),
            host_id,
            dict(result),
        )
        self.store.record_event(
            "task-completed",
            host_id,
            {"task_id": task.task_id, "attempts": task.attempts},
        )
        return {"task": self.task_payload(task)}

    def fail_task(
        self,
        host_id: str,
        peer_fingerprint: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.store.heartbeat_host(host_id, peer_fingerprint)
        task = self.store.fabric.fail_task(
            str(payload.get("task_id") or ""),
            host_id,
            str(payload.get("error") or "remote host task failed")[:1000],
            retry_delay_seconds=max(0.0, float(payload.get("retry_delay_seconds") or 0.0)),
        )
        self.store.record_event(
            "task-failed",
            host_id,
            {
                "task_id": task.task_id,
                "attempts": task.attempts,
                "state": task.state.value,
            },
        )
        return {"task": self.task_payload(task)}

    def status_payload(self) -> dict[str, Any]:
        return {
            "status": "online",
            "phase": "24B",
            "cluster_id": self.cluster_id,
            "uptime_seconds": round(time.time() - self.started_at, 4),
            "transport": {
                "tls_minimum": "1.2",
                "mutual_tls": True,
                "per_host_hmac_sha256": True,
                "replay_nonce_protection": True,
            },
            "summary": self.store.summary(self.cluster_id),
        }


class MultiHostHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        runtime: MultiHostControlPlane,
        cert_file: str | Path,
        key_file: str | Path,
        ca_file: str | Path,
    ) -> None:
        self.runtime = runtime
        super().__init__(address, _MultiHostHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cafile=str(ca_file))
        context.load_cert_chain(str(cert_file), str(key_file))
        self.socket = context.wrap_socket(self.socket, server_side=True)


class _MultiHostHandler(BaseHTTPRequestHandler):
    server: MultiHostHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "AIONEX-MultiHost/24B"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("invalid Content-Length") from None
        if not 0 <= length <= 1_000_000:
            raise ValueError("request body exceeds control-plane limit")
        return self.rfile.read(length) if length else b""

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authenticate(self, body: bytes) -> tuple[str, str]:
        host_id = str(self.headers.get(HOST_HEADER, "")).strip()
        authenticator = self.server.runtime.secrets.authenticator(host_id)
        verified = authenticator.verify(
            self.headers,
            self.command,
            self.path,
            body,
        )
        certificate = self.connection.getpeercert(binary_form=True)
        fingerprint = certificate_sha256(certificate)
        enrolled = self.server.runtime.store.get_host(verified.host_id)
        if enrolled.state == HostState.REVOKED:
            raise MultiHostAuthenticationError("host is revoked")
        if enrolled.certificate_sha256 != fingerprint:
            raise MultiHostAuthenticationError("peer certificate does not match host enrollment")
        if not self.server.runtime.store.consume_nonce(verified.host_id, verified.nonce):
            raise MultiHostAuthenticationError("request nonce was already used")
        return verified.host_id, fingerprint

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(
                HTTPStatus.OK,
                {"status": "ok", "phase": "24B", "cluster_id": self.server.runtime.cluster_id},
            )
            return
        if self.path != "/v1/cluster/status":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not-found"})
            return
        try:
            self._authenticate(b"")
        except sqlite3.Error:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "state-unavailable"})
            return
        except (KeyError, ValueError, PermissionError, MultiHostAuthenticationError):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        self._json(HTTPStatus.OK, self.server.runtime.status_payload())

    def do_POST(self) -> None:
        try:
            body = self._read_body()
            host_id, fingerprint = self._authenticate(body)
            decoded = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(decoded, dict):
                raise ValueError("payload must be an object")
        except sqlite3.Error:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "state-unavailable"})
            return
        except MultiHostAuthenticationError:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        except (KeyError, PermissionError):
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid-request"})
            return

        routes = {
            "/v1/hosts/register": lambda: self.server.runtime.register_host(host_id, fingerprint, decoded),
            "/v1/hosts/heartbeat": lambda: self.server.runtime.heartbeat_host(host_id, fingerprint),
            "/v1/leader/lease": lambda: self.server.runtime.leader_lease(host_id, fingerprint),
            "/v1/tasks/claim": lambda: self.server.runtime.claim_task(host_id, fingerprint),
            "/v1/tasks/renew": lambda: self.server.runtime.renew_task(host_id, fingerprint, decoded),
            "/v1/tasks/complete": lambda: self.server.runtime.complete_task(host_id, fingerprint, decoded),
            "/v1/tasks/fail": lambda: self.server.runtime.fail_task(host_id, fingerprint, decoded),
        }
        handler = routes.get(self.path)
        if handler is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not-found"})
            return
        try:
            result = handler()
        except sqlite3.Error:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "state-unavailable"})
            return
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not-found"})
            return
        except PermissionError:
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        except (ValueError, RuntimeError):
            self._json(HTTPStatus.CONFLICT, {"error": "request-rejected"})
            return
        self._json(HTTPStatus.OK, result)


def main() -> int:
    required = (
        "AIOS_MULTI_HOST_CLUSTER_ID",
        "AIOS_MULTI_HOST_STATE_PATH",
        "AIOS_MULTI_HOST_SECRET_DIR",
        "AIOS_MULTI_HOST_ENROLLMENT_MANIFEST",
        "AIOS_MULTI_HOST_CA_FILE",
        "AIOS_MULTI_HOST_CERT_FILE",
        "AIOS_MULTI_HOST_KEY_FILE",
    )
    values = {name: os.environ.get(name, "").strip() for name in required}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"missing control-plane environment variables: {missing}")
    runtime = MultiHostControlPlane(
        values["AIOS_MULTI_HOST_STATE_PATH"],
        values["AIOS_MULTI_HOST_CLUSTER_ID"],
        values["AIOS_MULTI_HOST_SECRET_DIR"],
        heartbeat_timeout=float(os.environ.get("AIOS_MULTI_HOST_HEARTBEAT_TIMEOUT", "6")),
        leader_lease_seconds=float(os.environ.get("AIOS_MULTI_HOST_LEADER_LEASE", "3")),
        task_lease_seconds=float(os.environ.get("AIOS_MULTI_HOST_TASK_LEASE", "3")),
    )
    runtime.load_enrollment_manifest(values["AIOS_MULTI_HOST_ENROLLMENT_MANIFEST"])
    host = os.environ.get("AIOS_MULTI_HOST_LISTEN_HOST", "0.0.0.0")
    port = int(os.environ.get("AIOS_MULTI_HOST_LISTEN_PORT", "9443"))
    server = MultiHostHTTPServer(
        (host, port),
        runtime,
        values["AIOS_MULTI_HOST_CERT_FILE"],
        values["AIOS_MULTI_HOST_KEY_FILE"],
        values["AIOS_MULTI_HOST_CA_FILE"],
    )
    stop = threading.Event()

    def terminate(signum: int, frame: object) -> None:
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    print(
        json.dumps(
            {"event": "control-plane-started", "cluster_id": runtime.cluster_id, "port": port},
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
