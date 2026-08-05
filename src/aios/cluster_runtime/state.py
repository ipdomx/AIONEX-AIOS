from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


class ClusterNodeState(StrEnum):
    STARTING = "starting"
    ONLINE = "online"
    DRAINING = "draining"
    OFFLINE = "offline"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ClusterNodeRecord:
    node_id: str
    service_url: str
    capabilities: tuple[str, ...]
    state: ClusterNodeState
    heartbeat_at: float
    started_at: float
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LeaderLease:
    cluster_id: str
    node_id: str
    term: int
    acquired_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class PeerObservation:
    observer_id: str
    peer_id: str
    healthy: bool
    tls_verified: bool
    authenticated: bool
    latency_ms: float
    error: str | None
    observed_at: float


class ClusterStateStore:
    """Shared SQLite cluster membership, discovery, leader, and audit state."""

    def __init__(self, path: str | Path) -> None:
        raw = Path(path)
        if not raw.is_absolute():
            raise ValueError("cluster state path must be absolute")
        raw.parent.mkdir(parents=True, exist_ok=True)
        self.path = raw.resolve(strict=False)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cluster_nodes (
                    node_id TEXT PRIMARY KEY,
                    service_url TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    started_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_cluster_nodes_state_heartbeat
                ON cluster_nodes(state, heartbeat_at);

                CREATE TABLE IF NOT EXISTS cluster_leader (
                    cluster_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    term INTEGER NOT NULL CHECK(term > 0),
                    acquired_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cluster_leader_history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cluster_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    term INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    recorded_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS peer_observations (
                    observer_id TEXT NOT NULL,
                    peer_id TEXT NOT NULL,
                    healthy INTEGER NOT NULL,
                    tls_verified INTEGER NOT NULL,
                    authenticated INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    error TEXT,
                    observed_at REAL NOT NULL,
                    PRIMARY KEY(observer_id, peer_id)
                );

                CREATE TABLE IF NOT EXISTS cluster_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    node_id TEXT,
                    details_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _load(value: str | None, default: Any) -> Any:
        return default if value in (None, "") else json.loads(value)

    @classmethod
    def _node(cls, row: sqlite3.Row) -> ClusterNodeRecord:
        return ClusterNodeRecord(
            node_id=str(row["node_id"]),
            service_url=str(row["service_url"]),
            capabilities=tuple(cls._load(row["capabilities_json"], [])),
            state=ClusterNodeState(str(row["state"])),
            heartbeat_at=float(row["heartbeat_at"]),
            started_at=float(row["started_at"]),
            metadata=dict(cls._load(row["metadata_json"], {})),
        )

    @staticmethod
    def _leader(row: sqlite3.Row) -> LeaderLease:
        return LeaderLease(
            cluster_id=str(row["cluster_id"]),
            node_id=str(row["node_id"]),
            term=int(row["term"]),
            acquired_at=float(row["acquired_at"]),
            expires_at=float(row["expires_at"]),
        )

    @staticmethod
    def _peer(row: sqlite3.Row) -> PeerObservation:
        return PeerObservation(
            observer_id=str(row["observer_id"]),
            peer_id=str(row["peer_id"]),
            healthy=bool(row["healthy"]),
            tls_verified=bool(row["tls_verified"]),
            authenticated=bool(row["authenticated"]),
            latency_ms=float(row["latency_ms"]),
            error=str(row["error"]) if row["error"] is not None else None,
            observed_at=float(row["observed_at"]),
        )

    def register_node(
        self,
        node_id: str,
        service_url: str,
        capabilities: Sequence[str],
        *,
        metadata: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> ClusterNodeRecord:
        if not node_id.strip() or not service_url.startswith("https://"):
            raise ValueError("node_id and an HTTPS service_url are required")
        normalized = tuple(sorted({item.strip().lower() for item in capabilities if item.strip()}))
        if not normalized:
            raise ValueError("at least one capability is required")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT started_at FROM cluster_nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
            started_at = float(existing["started_at"]) if existing is not None else timestamp
            connection.execute(
                """
                INSERT INTO cluster_nodes(
                    node_id, service_url, capabilities_json, state,
                    heartbeat_at, started_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    service_url=excluded.service_url,
                    capabilities_json=excluded.capabilities_json,
                    state=excluded.state,
                    heartbeat_at=excluded.heartbeat_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    node_id,
                    service_url,
                    self._dump(normalized),
                    ClusterNodeState.ONLINE.value,
                    timestamp,
                    started_at,
                    self._dump(dict(metadata or {})),
                ),
            )
            row = connection.execute(
                "SELECT * FROM cluster_nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
            self._event_locked(
                connection,
                "node-registered",
                node_id,
                {"service_url": service_url, "capabilities": list(normalized)},
                timestamp,
            )
        assert row is not None
        return self._node(row)

    def heartbeat_node(
        self,
        node_id: str,
        *,
        state: ClusterNodeState | None = None,
        now: float | None = None,
    ) -> ClusterNodeRecord:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM cluster_nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
            if row is None:
                raise KeyError(node_id)
            current = ClusterNodeState(str(row["state"]))
            next_state = state or (
                ClusterNodeState.ONLINE
                if current not in {ClusterNodeState.DRAINING, ClusterNodeState.FAILED}
                else current
            )
            connection.execute(
                "UPDATE cluster_nodes SET heartbeat_at=?, state=? WHERE node_id=?",
                (timestamp, next_state.value, node_id),
            )
            updated = connection.execute(
                "SELECT * FROM cluster_nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
        assert updated is not None
        return self._node(updated)

    def set_node_state(
        self,
        node_id: str,
        state: ClusterNodeState,
        *,
        now: float | None = None,
    ) -> ClusterNodeRecord:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            connection.execute(
                "UPDATE cluster_nodes SET state=?, heartbeat_at=? WHERE node_id=?",
                (state.value, timestamp, node_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise KeyError(node_id)
            row = connection.execute(
                "SELECT * FROM cluster_nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
            self._event_locked(
                connection,
                "node-state-changed",
                node_id,
                {"state": state.value},
                timestamp,
            )
        assert row is not None
        return self._node(row)

    def expire_stale_nodes(
        self,
        heartbeat_timeout: float,
        *,
        now: float | None = None,
    ) -> tuple[str, ...]:
        if heartbeat_timeout <= 0:
            raise ValueError("heartbeat_timeout must be positive")
        timestamp = float(now if now is not None else time.time())
        cutoff = timestamp - float(heartbeat_timeout)
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT node_id FROM cluster_nodes
                WHERE state=? AND heartbeat_at < ? ORDER BY node_id
                """,
                (ClusterNodeState.ONLINE.value, cutoff),
            ).fetchall()
            expired = tuple(str(row["node_id"]) for row in rows)
            for node_id in expired:
                connection.execute(
                    "UPDATE cluster_nodes SET state=? WHERE node_id=?",
                    (ClusterNodeState.OFFLINE.value, node_id),
                )
                self._event_locked(
                    connection,
                    "node-expired",
                    node_id,
                    {"heartbeat_timeout": heartbeat_timeout},
                    timestamp,
                )
        return expired

    def get_node(self, node_id: str) -> ClusterNodeRecord:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM cluster_nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(node_id)
        return self._node(row)

    def list_nodes(self) -> tuple[ClusterNodeRecord, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM cluster_nodes ORDER BY node_id"
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._node(row) for row in rows)

    def elect_or_renew_leader(
        self,
        cluster_id: str,
        node_id: str,
        *,
        lease_seconds: float = 5.0,
        now: float | None = None,
    ) -> LeaderLease:
        if not cluster_id.strip() or not node_id.strip():
            raise ValueError("cluster_id and node_id are required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            node = connection.execute(
                "SELECT state FROM cluster_nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
            if node is None or str(node["state"]) != ClusterNodeState.ONLINE.value:
                raise RuntimeError("only an online registered node can lead")
            current = connection.execute(
                "SELECT * FROM cluster_leader WHERE cluster_id=?",
                (cluster_id,),
            ).fetchone()
            if current is None:
                term = 1
                event = "leader-elected"
                acquired_at = timestamp
            elif str(current["node_id"]) == node_id:
                term = int(current["term"])
                event = "leader-renewed"
                acquired_at = float(current["acquired_at"])
            elif float(current["expires_at"]) <= timestamp:
                term = int(current["term"]) + 1
                event = "leader-failover"
                acquired_at = timestamp
            else:
                return self._leader(current)

            connection.execute(
                """
                INSERT INTO cluster_leader(
                    cluster_id, node_id, term, acquired_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    node_id=excluded.node_id,
                    term=excluded.term,
                    acquired_at=excluded.acquired_at,
                    expires_at=excluded.expires_at
                """,
                (
                    cluster_id,
                    node_id,
                    term,
                    acquired_at,
                    timestamp + float(lease_seconds),
                ),
            )
            if event != "leader-renewed":
                connection.execute(
                    """
                    INSERT INTO cluster_leader_history(
                        cluster_id, node_id, term, event, recorded_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (cluster_id, node_id, term, event, timestamp),
                )
                self._event_locked(
                    connection,
                    event,
                    node_id,
                    {"cluster_id": cluster_id, "term": term},
                    timestamp,
                )
            row = connection.execute(
                "SELECT * FROM cluster_leader WHERE cluster_id=?",
                (cluster_id,),
            ).fetchone()
        assert row is not None
        return self._leader(row)

    def get_leader(
        self,
        cluster_id: str,
        *,
        include_expired: bool = False,
        now: float | None = None,
    ) -> LeaderLease | None:
        timestamp = float(now if now is not None else time.time())
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM cluster_leader WHERE cluster_id=?",
                (cluster_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        leader = self._leader(row)
        if not include_expired and leader.expires_at <= timestamp:
            return None
        return leader

    def leader_history(self, cluster_id: str) -> tuple[dict[str, Any], ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT cluster_id, node_id, term, event, recorded_at
                FROM cluster_leader_history
                WHERE cluster_id=? ORDER BY event_id
                """,
                (cluster_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(
            {
                "cluster_id": str(row["cluster_id"]),
                "node_id": str(row["node_id"]),
                "term": int(row["term"]),
                "event": str(row["event"]),
                "recorded_at": float(row["recorded_at"]),
            }
            for row in rows
        )

    def record_peer_observation(
        self,
        observer_id: str,
        peer_id: str,
        *,
        healthy: bool,
        tls_verified: bool,
        authenticated: bool,
        latency_ms: float,
        error: str | None = None,
        now: float | None = None,
    ) -> PeerObservation:
        if not observer_id.strip() or not peer_id.strip() or observer_id == peer_id:
            raise ValueError("observer_id and a different peer_id are required")
        timestamp = float(now if now is not None else time.time())
        safe_error = str(error)[:500] if error else None
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO peer_observations(
                    observer_id, peer_id, healthy, tls_verified,
                    authenticated, latency_ms, error, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(observer_id, peer_id) DO UPDATE SET
                    healthy=excluded.healthy,
                    tls_verified=excluded.tls_verified,
                    authenticated=excluded.authenticated,
                    latency_ms=excluded.latency_ms,
                    error=excluded.error,
                    observed_at=excluded.observed_at
                """,
                (
                    observer_id,
                    peer_id,
                    int(bool(healthy)),
                    int(bool(tls_verified)),
                    int(bool(authenticated)),
                    max(0.0, float(latency_ms)),
                    safe_error,
                    timestamp,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM peer_observations
                WHERE observer_id=? AND peer_id=?
                """,
                (observer_id, peer_id),
            ).fetchone()
        assert row is not None
        return self._peer(row)

    def list_peer_observations(
        self,
        observer_id: str | None = None,
    ) -> tuple[PeerObservation, ...]:
        connection = self._connect()
        try:
            if observer_id is None:
                rows = connection.execute(
                    """
                    SELECT * FROM peer_observations
                    ORDER BY observer_id, peer_id
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM peer_observations
                    WHERE observer_id=? ORDER BY peer_id
                    """,
                    (observer_id,),
                ).fetchall()
        finally:
            connection.close()
        return tuple(self._peer(row) for row in rows)

    def record_event(
        self,
        event_type: str,
        node_id: str | None,
        details: Mapping[str, Any] | None = None,
        *,
        now: float | None = None,
    ) -> None:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            self._event_locked(
                connection,
                event_type,
                node_id,
                dict(details or {}),
                timestamp,
            )

    def list_events(self) -> tuple[dict[str, Any], ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT event_type, node_id, details_json, created_at
                FROM cluster_events ORDER BY event_id
                """
            ).fetchall()
        finally:
            connection.close()
        return tuple(
            {
                "event_type": str(row["event_type"]),
                "node_id": str(row["node_id"]) if row["node_id"] is not None else None,
                "details": dict(self._load(row["details_json"], {})),
                "created_at": float(row["created_at"]),
            }
            for row in rows
        )

    def summary(self, cluster_id: str, *, now: float | None = None) -> dict[str, Any]:
        nodes = self.list_nodes()
        leader = self.get_leader(cluster_id, now=now)
        observations = self.list_peer_observations()
        return {
            "cluster_id": cluster_id,
            "nodes_total": len(nodes),
            "nodes": {
                state.value: sum(node.state == state for node in nodes)
                for state in ClusterNodeState
            },
            "leader": (
                {
                    "node_id": leader.node_id,
                    "term": leader.term,
                    "expires_at": leader.expires_at,
                }
                if leader is not None
                else None
            ),
            "secure_peer_observations": sum(
                item.healthy and item.tls_verified and item.authenticated
                for item in observations
            ),
            "peer_observations_total": len(observations),
        }

    def _event_locked(
        self,
        connection: sqlite3.Connection,
        event_type: str,
        node_id: str | None,
        details: Mapping[str, Any],
        created_at: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO cluster_events(event_type, node_id, details_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, node_id, self._dump(dict(details)), created_at),
        )
