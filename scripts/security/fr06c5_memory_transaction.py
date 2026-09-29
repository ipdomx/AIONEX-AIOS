"""C5E2 durable intent/recovery engine; no production/kernel adapter is shipped.

Each explicit call performs at most one bound step. An uncertain action is never
replayed or automatically rolled back. Reconciliation observes only; restoration
is recorded only after every baseline fingerprint is independently observed.
The adapter must attest actual resource identity/ownership and closed authority.
Hashes detect incomplete/corrupt storage, not an attacker able to rewrite it.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import UUID

STEPS = (
    "prepare_encrypted_backing", "install_swap_unit", "install_tmp_unit",
    "disable_legacy_swap", "disable_legacy_fstab", "reload_units",
    "enable_memory_units", "attach_swap_loop", "activate_encrypted_swap", "activate_tmpfs",
)
MAX_RECORD = 65536
MAX_EVENTS = 256
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
EVENT_NAME = re.compile(r"[0-9]{8}\.json\Z")


class JournalRejected(RuntimeError):
    """Untrusted, incomplete, concurrently owned or inconsistent journal."""


class TransitionRejected(RuntimeError):
    """This explicit transition lacks the required current proof."""


class ActionUncertain(TransitionRejected):
    """An intent exists; use read-only reconciliation, never repeat its effect."""


def _uuid(value: str) -> None:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Canonical UUID required")


def _hash(value: str) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError("SHA256 required")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class BoundContext:
    source_commit: str
    boot_id: str
    maintenance_operation: str
    maintenance_generation: int
    host_state_receipt_sha256: str
    preflight_sha256: str
    boot_graph_sha256: str
    maintenance_closed: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.source_commit, str) or not HEX40.fullmatch(self.source_commit):
            raise ValueError("Exact source commit required")
        _uuid(self.boot_id)
        _uuid(self.maintenance_operation)
        if type(self.maintenance_generation) is not int or self.maintenance_generation < 1:
            raise ValueError("Exact maintenance generation required")
        if self.maintenance_closed is not True:
            raise ValueError("Closed maintenance required")
        for value in (self.host_state_receipt_sha256, self.preflight_sha256, self.boot_graph_sha256):
            _hash(value)


@dataclass(frozen=True)
class BoundStep:
    name: str
    before_sha256: str
    after_sha256: str

    def __post_init__(self) -> None:
        if self.name not in STEPS:
            raise ValueError("Unknown memory-control step")
        _hash(self.before_sha256)
        _hash(self.after_sha256)
        if self.before_sha256 == self.after_sha256:
            raise ValueError("Before and after must be distinguishable")


@dataclass(frozen=True)
class Plan:
    operation: str
    context: BoundContext
    steps: tuple[BoundStep, ...]
    created_at: int
    expires_at: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        _uuid(self.operation)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported journal schema")
        if not isinstance(self.context, BoundContext) or not isinstance(self.steps, tuple):
            raise TypeError("Typed context and immutable steps required")
        if not self.steps or any(not isinstance(step, BoundStep) for step in self.steps):
            raise ValueError("Explicit steps required")
        indices = [STEPS.index(step.name) for step in self.steps]
        if indices != sorted(set(indices)):
            raise ValueError("Steps must be unique and in reviewed order")
        if (type(self.created_at) is not int or type(self.expires_at) is not int
                or self.created_at <= 0 or not 0 < self.expires_at - self.created_at <= 900):
            raise ValueError("Bounded explicit validity window required")

    @classmethod
    def decode(cls, data: Any) -> Plan:
        if not isinstance(data, dict) or set(data) != {
            "operation", "context", "steps", "created_at", "expires_at", "schema_version"
        }:
            raise ValueError("Invalid plan fields")
        if not isinstance(data["steps"], list):
            raise TypeError("Invalid step list")
        return cls(operation=data["operation"], context=BoundContext(**data["context"]),
                   steps=tuple(BoundStep(**step) for step in data["steps"]),
                   created_at=data["created_at"], expires_at=data["expires_at"],
                   schema_version=data["schema_version"])


@dataclass(frozen=True)
class Observation:
    fingerprint: str
    identity_verified: bool
    owned_by_operation: bool

    def __post_init__(self) -> None:
        _hash(self.fingerprint)
        if type(self.identity_verified) is not bool or type(self.owned_by_operation) is not bool:
            raise ValueError("Explicit identity and ownership evidence required")


class MemoryAdapter(Protocol):
    """Must inspect real identities, not trust a command's exit code or a path.

    No default adapter exists. Production integration must additionally verify
    mapper/backing ownership, inode/mount topology, writer quiescence, secret
    handling and boot recovery; this protocol alone attests none of those.
    """
    def context(self) -> BoundContext: ...
    def observe(self, step: BoundStep, operation: str) -> Observation: ...
    def apply(self, step: BoundStep, operation: str) -> None: ...
    def undo(self, step: BoundStep, operation: str) -> None: ...


@dataclass
class State:
    phase: str
    applied: int
    pending: tuple[str, int] | None
    event_count: int


def _directory(path: Path) -> int:
    """Open every directory component without following a symlink."""
    if not path.is_absolute() or ".." in path.parts:
        raise JournalRejected("Absolute non-traversing journal parent required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _private_dir(fd: int) -> None:
    value = os.fstat(fd)
    if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) != 0o700:
        raise JournalRejected("Journal directory must be private and owned")


def _private_file(value: os.stat_result) -> None:
    if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1
            or value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) != 0o600):
        raise JournalRejected("Journal file is not private, regular and singly linked")


class Journal:
    """Locked directory of create-only, fsynced, chained records.

    A torn write, missing sequence, unexpected entry or stale directory identity
    blocks further effects. No truncation, reset, deletion or repair API exists.
    A successful append fsyncs the file and containing directory before returning.
    """
    def __init__(self, parent: Path, operation: str, *, create: Plan | None = None):
        self.parent = parent
        self.operation = operation
        self.parent_fd = self.fd = self.lock_fd = -1
        self.poisoned = False
        _uuid(operation)
        try:
            self.parent_fd = _directory(parent)
            _private_dir(self.parent_fd)
            if create is not None:
                if create.operation != operation:
                    raise JournalRejected("Operation and plan differ")
                os.mkdir(operation, mode=0o700, dir_fd=self.parent_fd)
                os.fsync(self.parent_fd)
            self.fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=self.parent_fd)
            _private_dir(self.fd)
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            if create is not None:
                flags |= os.O_CREAT | os.O_EXCL
            self.lock_fd = os.open(".lock", flags, 0o600, dir_fd=self.fd)
            _private_file(os.fstat(self.lock_fd))
            if os.fstat(self.lock_fd).st_size != 0:
                raise JournalRejected("Lock file differs")
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if create is not None:
                os.fsync(self.lock_fd)
                os.fsync(self.fd)
                self.plan = create
                self._write("plan.json", asdict(create))
                self._write("00000000.json", self._record(0, "0" * 64, "created", {}))
            else:
                self.plan = Plan.decode(self._read("plan.json"))
            if self.plan.operation != operation:
                raise JournalRejected("Reopened operation differs")
            self._records()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        for attribute in ("lock_fd", "fd", "parent_fd"):
            value = getattr(self, attribute)
            if value >= 0:
                os.close(value)
                setattr(self, attribute, -1)

    def _identity(self) -> None:
        if self.poisoned or self.fd < 0 or self.lock_fd < 0:
            raise JournalRejected("Closed or uncertain journal")
        current = _directory(self.parent)
        try:
            a, b = os.fstat(current), os.fstat(self.parent_fd)
            if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
                raise JournalRejected("Journal parent changed")
        finally:
            os.close(current)
        _private_dir(self.parent_fd)
        _private_dir(self.fd)
        actual = os.stat(self.operation, dir_fd=self.parent_fd, follow_symlinks=False)
        pinned = os.fstat(self.fd)
        if (actual.st_dev, actual.st_ino) != (pinned.st_dev, pinned.st_ino) or not stat.S_ISDIR(actual.st_mode):
            raise JournalRejected("Operation directory changed")
        actual = os.stat(".lock", dir_fd=self.fd, follow_symlinks=False)
        pinned = os.fstat(self.lock_fd)
        _private_file(actual)
        if (actual.st_dev, actual.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise JournalRejected("Operation lock changed")

    def _write(self, name: str, value: Any) -> None:
        self._identity()
        data = _canonical(value) + b"\n"
        if len(data) > MAX_RECORD:
            raise JournalRejected("Journal record exceeds bound")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        try:
            position = 0
            while position < len(data):
                count = os.write(fd, data[position:])
                if count <= 0:
                    raise OSError("Short journal write made no progress")
                position += count
            os.fsync(fd)
            os.fsync(self.fd)
        except BaseException:
            self.poisoned = True
            raise
        finally:
            os.close(fd)

    def _read(self, name: str) -> Any:
        self._identity()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            before = os.fstat(fd)
            _private_file(before)
            if not 0 < before.st_size <= MAX_RECORD:
                raise JournalRejected("Journal record has invalid size")
            data = bytearray()
            while len(data) <= MAX_RECORD:
                block = os.read(fd, min(8192, MAX_RECORD + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
            after = os.fstat(fd)
            # A read may update atime; only identity/content/security metadata
            # participates in the stability proof. Never ignore mtime or ctime.
            fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
                      "st_size", "st_mtime_ns", "st_ctime_ns")
            changed = any(getattr(before, key) != getattr(after, key) for key in fields)
            if len(data) != before.st_size or changed or not data.endswith(b"\n"):
                raise JournalRejected("Journal record changed or is incomplete")
            return json.loads(data, object_pairs_hook=_unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        except (ValueError, UnicodeError, TypeError) as exc:
            raise JournalRejected("Journal record cannot be decoded") from exc
        finally:
            os.close(fd)

    def _record(self, sequence: int, previous: str, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        body = {"sequence": sequence, "previous": previous, "operation": self.operation,
                "plan_sha256": _digest(asdict(self.plan)), "kind": kind, "data": data}
        return {"body": body, "sha256": _digest(body)}

    def _records(self) -> list[dict[str, Any]]:
        self._identity()
        if Plan.decode(self._read("plan.json")) != self.plan:
            raise JournalRejected("Bound plan changed")
        names = os.listdir(self.fd)
        events = sorted(name for name in names if EVENT_NAME.fullmatch(name))
        if (set(names) != {".lock", "plan.json", *events}
                or not 1 <= len(events) <= MAX_EVENTS
                or events != [f"{i:08d}.json" for i in range(len(events))]):
            raise JournalRejected("Journal has missing or unexpected records")
        previous = "0" * 64
        result = []
        for index, name in enumerate(events):
            record = self._read(name)
            if not isinstance(record, dict) or set(record) != {"body", "sha256"}:
                raise JournalRejected("Invalid chained record")
            body = record["body"]
            if (not isinstance(body, dict) or set(body) != {
                    "sequence", "previous", "operation", "plan_sha256", "kind", "data"}
                    or type(body["sequence"]) is not int or body["sequence"] != index
                    or body["previous"] != previous or body["operation"] != self.operation
                    or body["plan_sha256"] != _digest(asdict(self.plan))
                    or record["sha256"] != _digest(body)):
                raise JournalRejected("Journal chain differs")
            previous = record["sha256"]
            result.append(record)
        self._replay(result)
        return result

    def _replay(self, records: list[dict[str, Any]]) -> State:
        state = State("applying", 0, None, len(records))
        for n, record in enumerate(records):
            body = record["body"]
            kind, data = body["kind"], body["data"]
            if n == 0:
                if kind != "created" or data != {}:
                    raise JournalRejected("Missing creation event")
                continue
            if kind == "intent":
                if not isinstance(data, dict) or set(data) != {"direction", "index"} or state.pending is not None:
                    raise JournalRejected("Invalid action intent")
                direction, index = data["direction"], data["index"]
                if type(index) is not int or not 0 <= index < len(self.plan.steps):
                    raise JournalRejected("Invalid step index")
                if not ((direction == "apply" and state.phase == "applying" and index == state.applied)
                        or (direction == "undo" and state.phase == "rolling_back" and index == state.applied - 1)):
                    raise JournalRejected("Out-of-order action intent")
                state.pending = direction, index
            elif kind in {"settled", "reconciled"}:
                if (not isinstance(data, dict) or set(data) != {"direction", "index", "outcome", "fingerprint"}
                        or type(data["index"]) is not int
                        or state.pending != (data["direction"], data["index"])):
                    raise JournalRejected("Unbound outcome")
                step = self.plan.steps[data["index"]]
                outcome = data["outcome"]
                if outcome not in {"before", "after"} or data["fingerprint"] != getattr(step, outcome + "_sha256"):
                    raise JournalRejected("Outcome lacks bound proof")
                if kind == "settled" and outcome != ("after" if data["direction"] == "apply" else "before"):
                    raise JournalRejected("Unverified command completion")
                if data["direction"] == "apply":
                    state.applied += int(outcome == "after")
                    if kind == "reconciled":
                        state.phase = "halted"
                elif outcome == "before":
                    state.applied -= 1
                state.pending = None
            elif kind == "rollback_started":
                if data != {} or state.pending is not None or state.phase not in {"applying", "applied", "halted"}:
                    raise JournalRejected("Invalid recovery start")
                state.phase = "rolling_back"
            elif kind in {"applied_verified", "restored_verified"}:
                expected = "after" if kind == "applied_verified" else "before"
                fingerprints = [getattr(step, expected + "_sha256") for step in self.plan.steps]
                required_phase = "applying" if expected == "after" else "rolling_back"
                required_count = len(self.plan.steps) if expected == "after" else 0
                if (state.pending is not None or state.phase != required_phase or state.applied != required_count
                        or data != {"fingerprints": fingerprints}):
                    raise JournalRejected("Terminal state lacks complete verification")
                state.phase = "applied" if expected == "after" else "restored"
            else:
                raise JournalRejected("Unknown journal event")
        return state

    def state(self) -> State:
        return self._replay(self._records())

    def append(self, kind: str, data: dict[str, Any]) -> None:
        records = self._records()
        if len(records) >= MAX_EVENTS:
            raise JournalRejected("Journal event bound exceeded")
        record = self._record(len(records), records[-1]["sha256"], kind, data)
        self._replay([*records, record])
        self._write(f"{len(records):08d}.json", record)


class MemoryTransaction:
    def __init__(self, journal: Journal, adapter: MemoryAdapter, *, clock: Callable[[], float] = time.time):
        self.journal = journal
        self.plan = journal.plan
        self.adapter = adapter
        self.clock = clock

    def _context(self, *, forward: bool = False) -> None:
        if self.adapter.context() != self.plan.context:
            raise TransitionRejected("Bound source, boot, authority or evidence changed")
        if forward and not self.plan.created_at <= self.clock() <= self.plan.expires_at:
            raise TransitionRejected("Forward authorization window expired or not started")

    def _observation(self, step: BoundStep) -> str:
        result = self.adapter.observe(step, self.plan.operation)
        if not isinstance(result, Observation) or result.identity_verified is not True:
            raise TransitionRejected("Resource identity is unknown")
        if result.fingerprint == step.before_sha256:
            return "before"
        if result.fingerprint == step.after_sha256 and result.owned_by_operation is True:
            return "after"
        raise TransitionRejected("Resource is unknown, changed or not owned by this operation")

    def _perform(self, direction: str) -> State:
        state = self.journal.state()
        if state.pending is not None:
            raise ActionUncertain("Existing intent requires read-only reconciliation")
        forward = direction == "apply"
        if state.phase != ("applying" if forward else "rolling_back"):
            raise TransitionRejected("Explicit direction is not currently permitted")
        index = state.applied if forward else state.applied - 1
        if not 0 <= index < len(self.plan.steps):
            raise TransitionRejected("No next step; complete verification is required")
        step = self.plan.steps[index]
        self._context(forward=forward)
        if self._observation(step) != ("before" if forward else "after"):
            raise TransitionRejected("Effect already occurred or baseline changed; do not replay")
        self._context(forward=forward)
        # Both fsyncs must finish before the adapter is allowed to change anything.
        self.journal.append("intent", {"direction": direction, "index": index})
        try:
            self._context(forward=forward)
            (self.adapter.apply if forward else self.adapter.undo)(step, self.plan.operation)
            self._context()
            outcome = self._observation(step)
            if outcome != ("after" if forward else "before"):
                raise TransitionRejected("Command returned without its verified postcondition")
            self._context()
        except (OSError, ValueError, RuntimeError):
            raise ActionUncertain("Action outcome is uncertain; intent retained without replay") from None
        self.journal.append("settled", {"direction": direction, "index": index, "outcome": outcome,
                                        "fingerprint": getattr(step, outcome + "_sha256")})
        return self.journal.state()

    def apply_next(self) -> State:
        return self._perform("apply")

    def reconcile_pending(self) -> State:
        """Observe only; interrupted forward progress is halted, never replayed."""
        state = self.journal.state()
        if state.pending is None:
            raise TransitionRejected("No pending intent")
        self._context()
        direction, index = state.pending
        step = self.plan.steps[index]
        outcome = self._observation(step)
        self._context()
        self.journal.append("reconciled", {"direction": direction, "index": index, "outcome": outcome,
                                           "fingerprint": getattr(step, outcome + "_sha256")})
        return self.journal.state()

    def begin_rollback(self) -> State:
        self._context()
        self.journal.append("rollback_started", {})
        return self.journal.state()

    def undo_next(self) -> State:
        """Explicitly undo one verified owned step, in reverse order only."""
        return self._perform("undo")

    def _finish(self, restored: bool) -> State:
        state = self.journal.state()
        count = 0 if restored else len(self.plan.steps)
        phase = "rolling_back" if restored else "applying"
        if state.pending is not None or state.applied != count or state.phase != phase:
            raise TransitionRejected("Incomplete transaction cannot be finalized")
        self._context(forward=not restored)
        wanted = "before" if restored else "after"
        fingerprints = []
        for step in self.plan.steps:
            if self._observation(step) != wanted:
                raise TransitionRejected("Full final state not verified")
            fingerprints.append(getattr(step, wanted + "_sha256"))
        self._context(forward=not restored)
        self.journal.append("restored_verified" if restored else "applied_verified", {"fingerprints": fingerprints})
        return self.journal.state()

    def verify_applied(self) -> State:
        return self._finish(False)

    def verify_restored(self) -> State:
        return self._finish(True)
