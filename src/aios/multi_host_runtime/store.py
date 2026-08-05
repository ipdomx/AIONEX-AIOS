from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from aios.execution_fabric import ExecutionFabricStore, WorkerState

from .models import HostLeaderLease, HostRecord, HostState


class MultiHostControlStore:
    """Durable control-plane state for enrolled hosts, leader fencing, and replay protection."""

    def __init__(self, path: str | Path) -> None:
        raw = Path(path)
        if not raw.is_absolute():
            raise ValueError("control store path must be absolute")
        raw.parent.mkdir(parents=True, exist_ok=True)
        self.path = raw.resolve(strict=False)
        self.fabric = ExecutionFabricStore(self.path)
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
                CREATE TABLE IF NOT EXISTS multi_host_hosts (
                    host_id TEXT PRIMARY KEY,
                    service_url TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    certificate_sha256 TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    heartbeat_at REAL,
                    enrolled_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_multi_host_state_heartbeat
                ON multi_host_hosts(state, heartbeat_at);

                CREATE TABLE IF NOT EXISTS multi_host_leader (
                    cluster_id TEXT PRIMARY KEY,
                    host_id TEXT NOT NULL,
                    term INTEGER NOT NULL CHECK(term > 0),
                    fencing_token TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(host_id) REFERENCES multi_host_hosts(host_id)
                );

                CREATE TABLE IF NOT EXISTS multi_host_leader_history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cluster_id TEXT NOT NULL,
                    host_id TEXT NOT NULL,
                    term INTEGER NOT NULL,
                    fencing_token TEXT NOT NULL,
                    event TEXT NOT NULL,
                    recorded_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS multi_host_request_nonces (
                    host_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY(host_id, nonce),
                    FOREIGN KEY(host_id) REFERENCES multi_host_hosts(host_id)
                );

                CREATE INDEX IF NOT EXISTS idx_multi_host_nonces_expiry
                ON multi_host_request_nonces(expires_at);

                CREATE TABLE IF NOT EXISTS multi_host_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    host_id TEXT,
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
    def _host(cls, row: sqlite3.Row) -> HostRecord:
        return HostRecord(
            host_id=str(row["host_id"]),
            service_url=str(row["service_url"]),
            capabilities=tuple(cls._load(row["capabilities_json"], [])),
            certificate_sha256=str(row["certificate_sha256"]),
            state=HostState(str(row["state"])),
            heartbeat_at=(
                float(row["heartbeat_at"])
                if row["heartbeat_at"] is not None
                else None
            ),
            enrolled_at=float(row["enrolled_at"]),
            metadata=dict(cls._load(row["metadata_json"], {})),
        )

    @staticmethod
    def _leader(row: sqlite3.Row) -> HostLeaderLease:
        return HostLeaderLease(
            cluster_id=str(row["cluster_id"]),
            host_id=str(row["host_id"]),
            term=int(row["term"]),
            fencing_token=str(row["fencing_token"]),
            acquired_at=float(row["acquired_at"]),
            expires_at=float(row["expires_at"]),
        )

    def enroll_host(
        self,
        host_id: str,
        service_url: str,
        capabilities: Sequence[str],
        certificate_sha256: str,
        *,
        metadata: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> HostRecord:
        host = host_id.strip()
        fingerprint = certificate_sha256.strip().lower()
        normalized = tuple(sorted({item.strip().lower() for item in capabilities if item.strip()}))
        if not host or not service_url.startswith("https://"):
            raise ValueError("host_id and HTTPS service_url are required")
        if not normalized:
            raise ValueError("at least one host capability is required")
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("certificate SHA-256 fingerprint is invalid")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host,),
            ).fetchone()
            if existing is not None:
                record = self._host(existing)
                if (
                    record.certificate_sha256 != fingerprint
                    or record.service_url != service_url
                    or record.capabilities != normalized
                ):
                    raise ValueError("host identity is already enrolled with different attributes")
                return record
            connection.execute(
                """
                INSERT INTO multi_host_hosts(
                    host_id, service_url, capabilities_json,
                    certificate_sha256, state, heartbeat_at,
                    enrolled_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    host,
                    service_url,
                    self._dump(normalized),
                    fingerprint,
                    HostState.ENROLLED.value,
                    timestamp,
                    self._dump(dict(metadata or {})),
                ),
            )
            self._event_locked(
                connection,
                "host-enrolled",
                host,
                {"service_url": service_url, "capabilities": list(normalized)},
                timestamp,
            )
            row = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host,),
            ).fetchone()
        assert row is not None
        return self._host(row)

    def register_host(
        self,
        host_id: str,
        certificate_sha256: str,
        *,
        service_url: str,
        capabilities: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> HostRecord:
        timestamp = float(now if now is not None else time.time())
        fingerprint = certificate_sha256.strip().lower()
        normalized = tuple(sorted({item.strip().lower() for item in capabilities if item.strip()}))
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host_id,),
            ).fetchone()
            if row is None:
                raise KeyError(host_id)
            enrolled = self._host(row)
            if enrolled.state == HostState.REVOKED:
                raise PermissionError("host identity is revoked")
            if enrolled.certificate_sha256 != fingerprint:
                raise PermissionError("peer certificate fingerprint does not match enrollment")
            if enrolled.service_url != service_url or enrolled.capabilities != normalized:
                raise ValueError("host registration attributes do not match enrollment")
            merged_metadata = dict(enrolled.metadata)
            merged_metadata.update(dict(metadata or {}))
            connection.execute(
                """
                UPDATE multi_host_hosts
                SET state=?, heartbeat_at=?, metadata_json=?
                WHERE host_id=?
                """,
                (
                    HostState.ONLINE.value,
                    timestamp,
                    self._dump(merged_metadata),
                    host_id,
                ),
            )
            self._event_locked(
                connection,
                "host-registered",
                host_id,
                {"certificate_verified": True},
                timestamp,
            )
            updated = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host_id,),
            ).fetchone()
        assert updated is not None
        self.fabric.register_worker(
            host_id,
            normalized,
            max_concurrency=1,
            metadata={"service_url": service_url, "multi_host": True},
            now=timestamp,
        )
        return self._host(updated)

    def heartbeat_host(
        self,
        host_id: str,
        certificate_sha256: str,
        *,
        now: float | None = None,
    ) -> HostRecord:
        timestamp = float(now if now is not None else time.time())
        fingerprint = certificate_sha256.strip().lower()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host_id,),
            ).fetchone()
            if row is None:
                raise KeyError(host_id)
            current = self._host(row)
            if current.state == HostState.REVOKED:
                raise PermissionError("host identity is revoked")
            if current.certificate_sha256 != fingerprint:
                raise PermissionError("peer certificate fingerprint does not match enrollment")
            next_state = (
                current.state
                if current.state == HostState.DRAINING
                else HostState.ONLINE
            )
            connection.execute(
                "UPDATE multi_host_hosts SET state=?, heartbeat_at=? WHERE host_id=?",
                (next_state.value, timestamp, host_id),
            )
            updated = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host_id,),
            ).fetchone()
        assert updated is not None
        self.fabric.heartbeat_worker(host_id, now=timestamp)
        return self._host(updated)

    def set_host_state(self, host_id: str, state: HostState) -> HostRecord:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE multi_host_hosts SET state=? WHERE host_id=?",
                (state.value, host_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise KeyError(host_id)
            self._event_locked(
                connection,
                "host-state-changed",
                host_id,
                {"state": state.value},
                time.time(),
            )
            row = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host_id,),
            ).fetchone()
        assert row is not None
        worker_state = {
            HostState.ONLINE: WorkerState.ONLINE,
            HostState.DRAINING: WorkerState.DRAINING,
            HostState.OFFLINE: WorkerState.OFFLINE,
            HostState.REVOKED: WorkerState.FAILED,
            HostState.ENROLLED: WorkerState.OFFLINE,
        }[state]
        try:
            self.fabric.set_worker_state(host_id, worker_state)
        except KeyError:
            pass
        return self._host(row)

    def get_host(self, host_id: str) -> HostRecord:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(host_id)
        return self._host(row)

    def list_hosts(self) -> tuple[HostRecord, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM multi_host_hosts ORDER BY host_id"
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._host(row) for row in rows)

    def expire_stale_hosts(
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
                SELECT host_id FROM multi_host_hosts
                WHERE state=? AND heartbeat_at IS NOT NULL AND heartbeat_at < ?
                ORDER BY host_id
                """,
                (HostState.ONLINE.value, cutoff),
            ).fetchall()
            host_ids = tuple(str(row["host_id"]) for row in rows)
            if host_ids:
                connection.executemany(
                    "UPDATE multi_host_hosts SET state=? WHERE host_id=?",
                    [(HostState.OFFLINE.value, host_id) for host_id in host_ids],
                )
                for host_id in host_ids:
                    self._event_locked(
                        connection,
                        "host-expired",
                        host_id,
                        {"heartbeat_timeout": heartbeat_timeout},
                        timestamp,
                    )
        for host_id in host_ids:
            try:
                self.fabric.set_worker_state(host_id, WorkerState.OFFLINE)
            except KeyError:
                pass
        return host_ids

    def consume_nonce(
        self,
        host_id: str,
        nonce: str,
        *,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> bool:
        if not nonce or len(nonce) > 128:
            raise ValueError("request nonce is invalid")
        if ttl_seconds <= 0:
            raise ValueError("nonce ttl must be positive")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM multi_host_request_nonces WHERE expires_at <= ?",
                (timestamp,),
            )
            try:
                connection.execute(
                    """
                    INSERT INTO multi_host_request_nonces(host_id, nonce, expires_at)
                    VALUES (?, ?, ?)
                    """,
                    (host_id, nonce, timestamp + float(ttl_seconds)),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def elect_or_renew_leader(
        self,
        cluster_id: str,
        host_id: str,
        *,
        lease_seconds: float = 15.0,
        now: float | None = None,
    ) -> HostLeaderLease:
        if not cluster_id.strip() or not host_id.strip():
            raise ValueError("cluster_id and host_id are required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            host_row = connection.execute(
                "SELECT * FROM multi_host_hosts WHERE host_id=?",
                (host_id,),
            ).fetchone()
            if host_row is None:
                raise KeyError(host_id)
            host = self._host(host_row)
            if host.state != HostState.ONLINE:
                raise RuntimeError("only an online host may hold leadership")
            row = connection.execute(
                "SELECT * FROM multi_host_leader WHERE cluster_id=?",
                (cluster_id,),
            ).fetchone()
            if row is not None:
                current = self._leader(row)
                if current.expires_at > timestamp and current.host_id != host_id:
                    return current
                if current.host_id == host_id and current.expires_at > timestamp:
                    connection.execute(
                        "UPDATE multi_host_leader SET expires_at=? WHERE cluster_id=?",
                        (timestamp + float(lease_seconds), cluster_id),
                    )
                    updated = connection.execute(
                        "SELECT * FROM multi_host_leader WHERE cluster_id=?",
                        (cluster_id,),
                    ).fetchone()
                    assert updated is not None
                    return self._leader(updated)
                term = current.term + 1
                event = "leader-failover"
            else:
                history = connection.execute(
                    "SELECT MAX(term) AS term FROM multi_host_leader_history WHERE cluster_id=?",
                    (cluster_id,),
                ).fetchone()
                term = int(history["term"] or 0) + 1
                event = "leader-elected"
            fencing_token = f"{term}-{secrets.token_hex(16)}"
            connection.execute(
                """
                INSERT INTO multi_host_leader(
                    cluster_id, host_id, term, fencing_token,
                    acquired_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    host_id=excluded.host_id,
                    term=excluded.term,
                    fencing_token=excluded.fencing_token,
                    acquired_at=excluded.acquired_at,
                    expires_at=excluded.expires_at
                """,
                (
                    cluster_id,
                    host_id,
                    term,
                    fencing_token,
                    timestamp,
                    timestamp + float(lease_seconds),
                ),
            )
            connection.execute(
                """
                INSERT INTO multi_host_leader_history(
                    cluster_id, host_id, term, fencing_token, event, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cluster_id, host_id, term, fencing_token, event, timestamp),
            )
            self._event_locked(
                connection,
                event,
                host_id,
                {"cluster_id": cluster_id, "term": term},
                timestamp,
            )
            updated = connection.execute(
                "SELECT * FROM multi_host_leader WHERE cluster_id=?",
                (cluster_id,),
            ).fetchone()
        assert updated is not None
        return self._leader(updated)

    def get_leader(self, cluster_id: str, *, now: float | None = None) -> HostLeaderLease | None:
        timestamp = float(now if now is not None else time.time())
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM multi_host_leader WHERE cluster_id=?",
                (cluster_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        leader = self._leader(row)
        return leader if leader.expires_at > timestamp else None

    def leader_history(self, cluster_id: str) -> tuple[dict[str, Any], ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT cluster_id, host_id, term, fencing_token, event, recorded_at
                FROM multi_host_leader_history
                WHERE cluster_id=? ORDER BY term, event_id
                """,
                (cluster_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(
            {
                "cluster_id": str(row["cluster_id"]),
                "host_id": str(row["host_id"]),
                "term": int(row["term"]),
                "fencing_token": str(row["fencing_token"]),
                "event": str(row["event"]),
                "recorded_at": float(row["recorded_at"]),
            }
            for row in rows
        )

    def record_event(
        self,
        event_type: str,
        host_id: str | None,
        details: Mapping[str, Any] | None = None,
        *,
        now: float | None = None,
    ) -> None:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            self._event_locked(
                connection,
                event_type,
                host_id,
                dict(details or {}),
                timestamp,
            )

    def list_events(self, event_type: str | None = None) -> tuple[dict[str, Any], ...]:
        connection = self._connect()
        try:
            if event_type is None:
                rows = connection.execute(
                    "SELECT * FROM multi_host_events ORDER BY event_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM multi_host_events WHERE event_type=? ORDER BY event_id",
                    (event_type,),
                ).fetchall()
        finally:
            connection.close()
        return tuple(
            {
                "event_type": str(row["event_type"]),
                "host_id": str(row["host_id"]) if row["host_id"] is not None else None,
                "details": dict(self._load(row["details_json"], {})),
                "created_at": float(row["created_at"]),
            }
            for row in rows
        )

    def maintenance(
        self,
        heartbeat_timeout: float,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        timestamp = float(now if now is not None else time.time())
        expired_hosts = self.expire_stale_hosts(heartbeat_timeout, now=timestamp)
        expired_workers = self.fabric.expire_stale_workers(heartbeat_timeout, now=timestamp)
        recovered_tasks = self.fabric.recover_expired_leases(now=timestamp)
        return {
            "expired_hosts": list(expired_hosts),
            "expired_workers": list(expired_workers),
            "recovered_tasks": list(recovered_tasks),
        }

    def summary(self, cluster_id: str | None = None) -> dict[str, Any]:
        hosts = self.list_hosts()
        leader = self.get_leader(cluster_id) if cluster_id else None
        return {
            "hosts_total": len(hosts),
            "hosts": {
                state.value: sum(host.state == state for host in hosts)
                for state in HostState
            },
            "leader": (
                {
                    "host_id": leader.host_id,
                    "term": leader.term,
                    "expires_at": leader.expires_at,
                }
                if leader is not None
                else None
            ),
            "fabric": self.fabric.summary(),
        }

    def _event_locked(
        self,
        connection: sqlite3.Connection,
        event_type: str,
        host_id: str | None,
        details: Mapping[str, Any],
        timestamp: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO multi_host_events(event_type, host_id, details_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, host_id, self._dump(dict(details)), timestamp),
        )
