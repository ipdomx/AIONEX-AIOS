from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from .models import (
    DeadLetterRecord,
    TaskRecord,
    TaskState,
    WorkerRecord,
    WorkerState,
)


class ExecutionFabricStore:
    """SQLite-backed durable queue, worker registry, leases, locks and DLQ."""

    def __init__(self, path: str | Path) -> None:
        raw = Path(path)
        if not raw.is_absolute():
            raise ValueError("store path must be absolute")
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
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    capabilities_json TEXT NOT NULL,
                    max_concurrency INTEGER NOT NULL CHECK(max_concurrency > 0),
                    current_load INTEGER NOT NULL DEFAULT 0 CHECK(current_load >= 0),
                    state TEXT NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    max_attempts INTEGER NOT NULL CHECK(max_attempts > 0),
                    available_at REAL NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    result_json TEXT,
                    error TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(lease_owner) REFERENCES workers(worker_id)
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_claim
                ON tasks(state, available_at, priority, created_at);

                CREATE INDEX IF NOT EXISTS idx_tasks_execution
                ON tasks(execution_id, created_at);

                CREATE TABLE IF NOT EXISTS dead_letters (
                    task_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    final_error TEXT NOT NULL,
                    failed_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_locks (
                    lock_name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _dump(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _load(payload: str | None, default: Any) -> Any:
        if payload in (None, ""):
            return default
        return json.loads(payload)

    @classmethod
    def _worker_from_row(cls, row: sqlite3.Row) -> WorkerRecord:
        return WorkerRecord(
            worker_id=str(row["worker_id"]),
            capabilities=tuple(cls._load(row["capabilities_json"], [])),
            max_concurrency=int(row["max_concurrency"]),
            current_load=int(row["current_load"]),
            state=WorkerState(str(row["state"])),
            heartbeat_at=float(row["heartbeat_at"]),
            metadata=dict(cls._load(row["metadata_json"], {})),
        )

    @classmethod
    def _task_from_row(cls, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=str(row["task_id"]),
            execution_id=str(row["execution_id"]),
            name=str(row["name"]),
            capability=str(row["capability"]),
            payload=dict(cls._load(row["payload_json"], {})),
            priority=int(row["priority"]),
            state=TaskState(str(row["state"])),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            available_at=float(row["available_at"]),
            lease_owner=str(row["lease_owner"]) if row["lease_owner"] is not None else None,
            lease_expires_at=(
                float(row["lease_expires_at"])
                if row["lease_expires_at"] is not None
                else None
            ),
            result=(
                dict(cls._load(row["result_json"], {}))
                if row["result_json"] is not None
                else None
            ),
            error=str(row["error"]) if row["error"] is not None else None,
            idempotency_key=str(row["idempotency_key"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def register_worker(
        self,
        worker_id: str,
        capabilities: Sequence[str],
        *,
        max_concurrency: int = 1,
        metadata: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> WorkerRecord:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        normalized = tuple(sorted({item.strip().lower() for item in capabilities if item.strip()}))
        if not normalized:
            raise ValueError("at least one worker capability is required")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO workers(
                    worker_id, capabilities_json, max_concurrency,
                    current_load, state, heartbeat_at, metadata_json
                ) VALUES (?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    capabilities_json=excluded.capabilities_json,
                    max_concurrency=excluded.max_concurrency,
                    state=excluded.state,
                    heartbeat_at=excluded.heartbeat_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    worker_id,
                    self._dump(normalized),
                    int(max_concurrency),
                    WorkerState.ONLINE.value,
                    timestamp,
                    self._dump(metadata or {}),
                ),
            )
            row = connection.execute(
                "SELECT * FROM workers WHERE worker_id=?", (worker_id,)
            ).fetchone()
        assert row is not None
        return self._worker_from_row(row)

    def heartbeat_worker(
        self,
        worker_id: str,
        *,
        state: WorkerState | None = None,
        now: float | None = None,
    ) -> WorkerRecord:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM workers WHERE worker_id=?", (worker_id,)
            ).fetchone()
            if row is None:
                raise KeyError(worker_id)
            current_state = WorkerState(str(row["state"]))
            next_state = state or (
                WorkerState.ONLINE
                if current_state not in {WorkerState.DRAINING, WorkerState.FAILED}
                else current_state
            )
            connection.execute(
                "UPDATE workers SET heartbeat_at=?, state=? WHERE worker_id=?",
                (timestamp, next_state.value, worker_id),
            )
            updated = connection.execute(
                "SELECT * FROM workers WHERE worker_id=?", (worker_id,)
            ).fetchone()
        assert updated is not None
        return self._worker_from_row(updated)

    def set_worker_state(self, worker_id: str, state: WorkerState) -> WorkerRecord:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE workers SET state=? WHERE worker_id=?",
                (state.value, worker_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise KeyError(worker_id)
            row = connection.execute(
                "SELECT * FROM workers WHERE worker_id=?", (worker_id,)
            ).fetchone()
        assert row is not None
        return self._worker_from_row(row)

    def expire_stale_workers(
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
                SELECT worker_id FROM workers
                WHERE state=? AND heartbeat_at < ?
                ORDER BY worker_id
                """,
                (WorkerState.ONLINE.value, cutoff),
            ).fetchall()
            worker_ids = tuple(str(row["worker_id"]) for row in rows)
            if worker_ids:
                connection.executemany(
                    "UPDATE workers SET state=? WHERE worker_id=?",
                    [(WorkerState.OFFLINE.value, worker_id) for worker_id in worker_ids],
                )
        return worker_ids

    def get_worker(self, worker_id: str) -> WorkerRecord:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM workers WHERE worker_id=?", (worker_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(worker_id)
        return self._worker_from_row(row)

    def list_workers(self) -> tuple[WorkerRecord, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM workers ORDER BY worker_id"
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._worker_from_row(row) for row in rows)

    def submit_task(
        self,
        *,
        execution_id: str,
        name: str,
        capability: str,
        payload: dict[str, Any],
        idempotency_key: str,
        priority: int = 100,
        max_attempts: int = 2,
        now: float | None = None,
    ) -> TaskRecord:
        if not execution_id.strip() or not name.strip() or not capability.strip():
            raise ValueError("execution_id, name and capability are required")
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        timestamp = float(now if now is not None else time.time())
        task_id = uuid.uuid4().hex
        payload_json = self._dump(payload)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM tasks WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["execution_id"]) != execution_id
                    or str(existing["name"]) != name
                    or str(existing["capability"]) != capability.lower()
                    or str(existing["payload_json"]) != payload_json
                ):
                    raise ValueError("idempotency key is already bound to different task data")
                return self._task_from_row(existing)
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, execution_id, name, capability, payload_json,
                    priority, state, attempts, max_attempts, available_at,
                    lease_owner, lease_expires_at, result_json, error,
                    idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?)
                """,
                (
                    task_id,
                    execution_id,
                    name,
                    capability.lower(),
                    payload_json,
                    int(priority),
                    TaskState.PENDING.value,
                    int(max_attempts),
                    timestamp,
                    idempotency_key,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        assert row is not None
        return self._task_from_row(row)

    def claim_task(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 30.0,
        heartbeat_timeout: float = 30.0,
        now: float | None = None,
    ) -> TaskRecord | None:
        if lease_seconds <= 0 or heartbeat_timeout <= 0:
            raise ValueError("lease and heartbeat timeouts must be positive")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            self._recover_expired_locked(connection, timestamp)
            worker_row = connection.execute(
                "SELECT * FROM workers WHERE worker_id=?", (worker_id,)
            ).fetchone()
            if worker_row is None:
                raise KeyError(worker_id)
            worker = self._worker_from_row(worker_row)
            if worker.state != WorkerState.ONLINE:
                return None
            if timestamp - worker.heartbeat_at > heartbeat_timeout:
                connection.execute(
                    "UPDATE workers SET state=? WHERE worker_id=?",
                    (WorkerState.OFFLINE.value, worker_id),
                )
                return None
            if worker.current_load >= worker.max_concurrency:
                return None

            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE state IN (?, ?) AND available_at <= ?
                ORDER BY priority ASC, created_at ASC, task_id ASC
                LIMIT 256
                """,
                (
                    TaskState.PENDING.value,
                    TaskState.RETRY_WAIT.value,
                    timestamp,
                ),
            ).fetchall()
            selected = next(
                (
                    row
                    for row in rows
                    if str(row["capability"]) in set(worker.capabilities)
                ),
                None,
            )
            if selected is None:
                return None
            task_id = str(selected["task_id"])
            connection.execute(
                """
                UPDATE tasks SET
                    state=?, attempts=attempts+1, lease_owner=?,
                    lease_expires_at=?, updated_at=?, error=NULL
                WHERE task_id=? AND state IN (?, ?)
                """,
                (
                    TaskState.LEASED.value,
                    worker_id,
                    timestamp + float(lease_seconds),
                    timestamp,
                    task_id,
                    TaskState.PENDING.value,
                    TaskState.RETRY_WAIT.value,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                return None
            connection.execute(
                "UPDATE workers SET current_load=current_load+1 WHERE worker_id=?",
                (worker_id,),
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        assert row is not None
        return self._task_from_row(row)

    def heartbeat_task(
        self,
        task_id: str,
        worker_id: str,
        *,
        lease_seconds: float = 30.0,
        now: float | None = None,
    ) -> TaskRecord:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE tasks SET lease_expires_at=?, updated_at=?
                WHERE task_id=? AND state=? AND lease_owner=?
                """,
                (
                    timestamp + float(lease_seconds),
                    timestamp,
                    task_id,
                    TaskState.LEASED.value,
                    worker_id,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise RuntimeError("task lease is not owned by this worker")
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        assert row is not None
        return self._task_from_row(row)

    def complete_task(
        self,
        task_id: str,
        worker_id: str,
        result: dict[str, Any],
        *,
        now: float | None = None,
    ) -> TaskRecord:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["state"] != TaskState.LEASED.value or row["lease_owner"] != worker_id:
                raise RuntimeError("task is not leased by this worker")
            connection.execute(
                """
                UPDATE tasks SET state=?, result_json=?, error=NULL,
                    lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                WHERE task_id=?
                """,
                (
                    TaskState.SUCCEEDED.value,
                    self._dump(result),
                    timestamp,
                    task_id,
                ),
            )
            self._decrement_worker_load_locked(connection, worker_id)
            updated = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        assert updated is not None
        return self._task_from_row(updated)

    def fail_task(
        self,
        task_id: str,
        worker_id: str,
        error: str,
        *,
        retry_delay_seconds: float = 0.0,
        now: float | None = None,
    ) -> TaskRecord:
        timestamp = float(now if now is not None else time.time())
        safe_error = str(error)[:1000] or "worker task failed"
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["state"] != TaskState.LEASED.value or row["lease_owner"] != worker_id:
                raise RuntimeError("task is not leased by this worker")
            attempts = int(row["attempts"])
            max_attempts = int(row["max_attempts"])
            if attempts < max_attempts:
                next_state = TaskState.RETRY_WAIT
                available_at = timestamp + max(0.0, float(retry_delay_seconds))
            else:
                next_state = TaskState.DEAD_LETTER
                available_at = timestamp
                self._insert_dead_letter_locked(connection, row, safe_error, timestamp)
            connection.execute(
                """
                UPDATE tasks SET state=?, error=?, available_at=?,
                    lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                WHERE task_id=?
                """,
                (
                    next_state.value,
                    safe_error,
                    available_at,
                    timestamp,
                    task_id,
                ),
            )
            self._decrement_worker_load_locked(connection, worker_id)
            updated = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        assert updated is not None
        return self._task_from_row(updated)

    def recover_expired_leases(self, *, now: float | None = None) -> tuple[str, ...]:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            return self._recover_expired_locked(connection, timestamp)

    def _recover_expired_locked(
        self,
        connection: sqlite3.Connection,
        timestamp: float,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            """
            SELECT * FROM tasks
            WHERE state=? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
            ORDER BY task_id
            """,
            (TaskState.LEASED.value, timestamp),
        ).fetchall()
        recovered: list[str] = []
        for row in rows:
            task_id = str(row["task_id"])
            worker_id = str(row["lease_owner"]) if row["lease_owner"] is not None else None
            attempts = int(row["attempts"])
            max_attempts = int(row["max_attempts"])
            error = "task lease expired before completion"
            if attempts < max_attempts:
                next_state = TaskState.RETRY_WAIT
            else:
                next_state = TaskState.DEAD_LETTER
                self._insert_dead_letter_locked(connection, row, error, timestamp)
            connection.execute(
                """
                UPDATE tasks SET state=?, error=?, available_at=?,
                    lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                WHERE task_id=?
                """,
                (next_state.value, error, timestamp, timestamp, task_id),
            )
            if worker_id:
                self._decrement_worker_load_locked(connection, worker_id)
            recovered.append(task_id)
        return tuple(recovered)

    @staticmethod
    def _decrement_worker_load_locked(
        connection: sqlite3.Connection,
        worker_id: str,
    ) -> None:
        connection.execute(
            """
            UPDATE workers
            SET current_load=CASE WHEN current_load > 0 THEN current_load-1 ELSE 0 END
            WHERE worker_id=?
            """,
            (worker_id,),
        )

    def _insert_dead_letter_locked(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        error: str,
        failed_at: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO dead_letters(
                task_id, execution_id, name, capability, payload_json,
                attempts, final_error, failed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                attempts=excluded.attempts,
                final_error=excluded.final_error,
                failed_at=excluded.failed_at
            """,
            (
                row["task_id"],
                row["execution_id"],
                row["name"],
                row["capability"],
                row["payload_json"],
                row["attempts"],
                error,
                failed_at,
            ),
        )

    def cancel_task(self, task_id: str, *, now: float | None = None) -> TaskRecord:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            state = TaskState(str(row["state"]))
            if state == TaskState.LEASED and row["lease_owner"] is not None:
                self._decrement_worker_load_locked(connection, str(row["lease_owner"]))
            if state not in {TaskState.SUCCEEDED, TaskState.DEAD_LETTER}:
                connection.execute(
                    """
                    UPDATE tasks SET state=?, lease_owner=NULL,
                        lease_expires_at=NULL, updated_at=? WHERE task_id=?
                    """,
                    (TaskState.CANCELLED.value, timestamp, task_id),
                )
            updated = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        assert updated is not None
        return self._task_from_row(updated)

    def get_task(self, task_id: str) -> TaskRecord:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def list_tasks(self, execution_id: str | None = None) -> tuple[TaskRecord, ...]:
        connection = self._connect()
        try:
            if execution_id is None:
                rows = connection.execute(
                    "SELECT * FROM tasks ORDER BY created_at, task_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM tasks WHERE execution_id=?
                    ORDER BY created_at, task_id
                    """,
                    (execution_id,),
                ).fetchall()
        finally:
            connection.close()
        return tuple(self._task_from_row(row) for row in rows)

    def list_dead_letters(
        self, execution_id: str | None = None
    ) -> tuple[DeadLetterRecord, ...]:
        connection = self._connect()
        try:
            if execution_id is None:
                rows = connection.execute(
                    "SELECT * FROM dead_letters ORDER BY failed_at, task_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM dead_letters WHERE execution_id=?
                    ORDER BY failed_at, task_id
                    """,
                    (execution_id,),
                ).fetchall()
        finally:
            connection.close()
        return tuple(
            DeadLetterRecord(
                task_id=str(row["task_id"]),
                execution_id=str(row["execution_id"]),
                name=str(row["name"]),
                capability=str(row["capability"]),
                payload=dict(self._load(row["payload_json"], {})),
                attempts=int(row["attempts"]),
                final_error=str(row["final_error"]),
                failed_at=float(row["failed_at"]),
            )
            for row in rows
        )

    def acquire_lock(
        self,
        lock_name: str,
        owner: str,
        *,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> bool:
        if not lock_name.strip() or not owner.strip():
            raise ValueError("lock name and owner are required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT owner, expires_at FROM execution_locks WHERE lock_name=?",
                (lock_name,),
            ).fetchone()
            if row is not None and float(row["expires_at"]) > timestamp and str(row["owner"]) != owner:
                return False
            connection.execute(
                """
                INSERT INTO execution_locks(lock_name, owner, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(lock_name) DO UPDATE SET
                    owner=excluded.owner,
                    expires_at=excluded.expires_at
                """,
                (lock_name, owner, timestamp + float(ttl_seconds)),
            )
        return True

    def renew_lock(
        self,
        lock_name: str,
        owner: str,
        *,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> bool:
        timestamp = float(now if now is not None else time.time())
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE execution_locks SET expires_at=?
                WHERE lock_name=? AND owner=? AND expires_at > ?
                """,
                (timestamp + float(ttl_seconds), lock_name, owner, timestamp),
            )
            changed = connection.execute("SELECT changes()").fetchone()[0]
        return changed == 1

    def release_lock(self, lock_name: str, owner: str) -> bool:
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM execution_locks WHERE lock_name=? AND owner=?",
                (lock_name, owner),
            )
            changed = connection.execute("SELECT changes()").fetchone()[0]
        return changed == 1

    def summary(self, execution_id: str | None = None) -> dict[str, Any]:
        tasks = self.list_tasks(execution_id)
        workers = self.list_workers()
        dead_letters = self.list_dead_letters(execution_id)
        return {
            "tasks_total": len(tasks),
            "tasks": {
                state.value: sum(task.state == state for task in tasks)
                for state in TaskState
            },
            "workers_total": len(workers),
            "workers": {
                state.value: sum(worker.state == state for worker in workers)
                for state in WorkerState
            },
            "dead_letters": len(dead_letters),
        }
