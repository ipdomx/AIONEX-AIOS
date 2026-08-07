from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from .db import Database


@dataclass(frozen=True)
class ConnectionCheck:
    reachable: bool
    latency_ms: float
    status: str
    details: dict


class ConnectorRegistry:
    """Extensible registry for project servers; secrets stay in environment variables."""

    ALLOWED_TYPES = {'http', 'tcp'}

    def __init__(self, db: Database):
        self.db = db

    def register(self, project: str, name: str, connector_type: str, endpoint: str,
                 config: dict | None = None) -> None:
        if connector_type not in self.ALLOWED_TYPES:
            raise ValueError(f'Unsupported connector type: {connector_type}')
        self._validate_endpoint(connector_type, endpoint)
        with self.db.connect() as conn:
            conn.execute(
                '''INSERT INTO connector_profiles(project, name, connector_type, endpoint, config)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(project, name) DO UPDATE SET connector_type=excluded.connector_type,
                   endpoint=excluded.endpoint, config=excluded.config, enabled=1''',
                (project, name, connector_type, endpoint,
                 json.dumps(config or {}, ensure_ascii=False, sort_keys=True)),
            )

    def list(self, project: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                'SELECT * FROM connector_profiles WHERE project = ? ORDER BY name', (project,)
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _validate_endpoint(connector_type: str, endpoint: str) -> None:
        if connector_type == 'http':
            parsed = urlparse(endpoint)
            if (
                parsed.scheme not in {'http', 'https'}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError('HTTP endpoint must be a plain http(s) URL without embedded credentials or fragments')
        elif connector_type == 'tcp':
            host, sep, port = endpoint.rpartition(':')
            if not sep or not host or not port.isdigit() or not (1 <= int(port) <= 65535):
                raise ValueError('TCP endpoint must use host:port')

    def check(self, project: str, name: str, timeout: float = 5.0) -> ConnectionCheck:
        import time
        with self.db.connect() as conn:
            row = conn.execute(
                '''SELECT connector_type, endpoint, config FROM connector_profiles
                   WHERE project = ? AND name = ? AND enabled = 1''',
                (project, name),
            ).fetchone()
        if row is None:
            raise KeyError(f'Unknown connector: {project}/{name}')
        started = time.perf_counter()
        try:
            if row['connector_type'] == 'http':
                request = urllib.request.Request(row['endpoint'], method='GET', headers={'User-Agent': 'AIOS/1.1'})
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    details = {'http_status': response.status, 'content_type': response.headers.get('Content-Type')}
                    status = 'healthy' if 200 <= response.status < 400 else 'unhealthy'
                    reachable = 200 <= response.status < 500
            else:
                host, port = row['endpoint'].rpartition(':')[0], int(row['endpoint'].rpartition(':')[2])
                with socket.create_connection((host, port), timeout=timeout):
                    details = {'host': host, 'port': port}
                    status, reachable = 'reachable', True
        except (OSError, urllib.error.URLError) as exc:
            details = {'error_type': type(exc).__name__, 'message': str(exc)}
            status, reachable = 'unreachable', False
        latency = (time.perf_counter() - started) * 1000
        return ConnectionCheck(reachable, round(latency, 2), status, details)
