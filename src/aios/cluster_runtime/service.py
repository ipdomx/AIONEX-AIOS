from __future__ import annotations

import json
import ssl
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from .auth import ClusterAuthenticationError, ClusterAuthenticator


class ClusterRuntimeProtocol(Protocol):
    node_id: str
    authenticator: ClusterAuthenticator

    def status_payload(self) -> dict[str, Any]: ...

    def receive_peer_heartbeat(
        self,
        identity_node_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class SecureClusterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        runtime: ClusterRuntimeProtocol,
        cert_file: str | Path,
        key_file: str | Path,
    ) -> None:
        self.runtime = runtime
        super().__init__(address, _ClusterHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert_file), str(key_file))
        self.socket = context.wrap_socket(self.socket, server_side=True)


class _ClusterHandler(BaseHTTPRequestHandler):
    server: SecureClusterHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "AIONEX-Cluster/24A"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("invalid Content-Length") from None
        if not 0 <= length <= 1_000_000:
            raise ValueError("request body exceeds cluster API limit")
        return self.rfile.read(length) if length else b""

    def _json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _identity(self, body: bytes):
        return self.server.runtime.authenticator.verify(
            self.headers,
            self.command,
            self.path,
            body,
        )

    def do_GET(self) -> None:
        if self.path == "/healthz":
            status = self.server.runtime.status_payload()
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "node_id": self.server.runtime.node_id,
                    "leader": status.get("leader"),
                },
            )
            return
        if self.path != "/v1/cluster/status":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not-found"})
            return
        try:
            self._identity(b"")
        except ClusterAuthenticationError:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        self._json(HTTPStatus.OK, self.server.runtime.status_payload())

    def do_POST(self) -> None:
        try:
            body = self._read_body()
            identity = self._identity(body)
        except (ValueError, ClusterAuthenticationError):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            decoded = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid-json"})
            return
        if not isinstance(decoded, dict):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid-payload"})
            return
        if self.path == "/v1/cluster/heartbeat":
            try:
                result = self.server.runtime.receive_peer_heartbeat(
                    identity.node_id,
                    decoded,
                )
            except (ValueError, KeyError, RuntimeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "heartbeat-rejected"})
                return
            self._json(HTTPStatus.OK, result)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not-found"})
