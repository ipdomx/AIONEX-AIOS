"""Local, non-deployed exclusive-effect guard for future reviewed FR-06 callers.

This module performs ONLY private journal/lock I/O plus explicitly supplied
callbacks. It has no CLI, shell runner, provider client, host action or installer.
All participating fixed callers must use the SAME accepted directory, revalidate
actual source/authority inside this scope, and enforce their own approval,
security, evidence and activation gates. This lock grants none of those gates.
A durable intent without a result is never cleared or retried here, even after
process death, timeout, old heartbeat or a later successful lock acquisition.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

TASK_ID = "6abd4c859254819191f562715e18c916"
SCHEMA = "aionex.fr06-exclusive-effect.v1"
MAX_JOURNAL_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 8192
INVOCATIONS = frozenset({"interactive", "scheduled", "watchdog"})
ACTIONS = frozenset({"source_merge", "source_sync", "service_lifecycle",
                     "maintenance_transition", "provider_settlement",
                     "host_state", "memory_activation", "reboot_recovery"})


class GuardBlocked(RuntimeError):
    """Ownership, journal or context is not proven; perform no further effect."""


class ConcurrentOwner(GuardBlocked):
    pass


class UncertainEffect(GuardBlocked):
    pass


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise GuardBlocked(message)


def _hex(value: object, size: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % size, value) is not None


def _uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _canon(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError):
        raise GuardBlocked("noncanonical journal data") from None


def _digest(value: object) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


@dataclass(frozen=True)
class Binding:
    source_commit: str
    main_commit: str
    boot_id: str
    operation_id: str
    generation: int
    source_clean: bool
    maintenance_status: str

    def validate(self) -> None:
        _need(_hex(self.source_commit, 40) and self.source_commit == self.main_commit,
              "source must match exact main")
        _need(self.source_clean is True, "source is not clean")
        _need(_uuid(self.boot_id) and _uuid(self.operation_id), "invalid boot/operation identity")
        _need(type(self.generation) is int and self.generation >= 8, "invalid generation")
        _need(self.maintenance_status == "closed", "maintenance is not closed")


@dataclass(frozen=True)
class SyncBinding:
    """Keep remote target and still-old local main distinct during fast-forward.

    This is valid ONLY for source_sync to main_commit. The fixed caller must
    separately verify protected exact-main checks and forward ancestry, while
    holding the guard. This type neither claims those checks nor fetches code.
    """
    source_commit: str
    local_main_commit: str
    main_commit: str
    boot_id: str
    operation_id: str
    generation: int
    source_clean: bool
    maintenance_status: str

    def validate(self) -> None:
        Binding(self.source_commit, self.local_main_commit, self.boot_id,
                self.operation_id, self.generation, self.source_clean,
                self.maintenance_status).validate()
        _need(_hex(self.main_commit, 40), "exact remote main target required")


@dataclass(frozen=True)
class ObservedResult:
    """Caller-observed outcome, NOT automatic production acceptance.

    evidence_sha256 must identify a genuinely retained sanitized receipt.
    A callback timeout or uncertain outcome must raise, not return no_effect.
    """
    outcome: str
    evidence_sha256: str

    def validate(self) -> None:
        _need(isinstance(self.outcome, str) and self.outcome in {"observed_complete", "observed_no_effect"}, "outcome is uncertain")
        _need(_hex(self.evidence_sha256, 64), "exact evidence digest required")


def _binding(raw: object) -> Binding | SyncBinding:
    _need(isinstance(raw, dict), "invalid binding fields")
    cls = SyncBinding if "local_main_commit" in raw else Binding
    _need(set(raw) == set(cls.__dataclass_fields__), "invalid binding fields")
    value = cls(**raw)
    value.validate()
    return value


def _action_binding(value: Binding | SyncBinding, action: str, target: str) -> None:
    if type(value) is SyncBinding:
        _need(action == "source_sync" and target == value.main_commit,
              "sync binding is restricted to exact remote-main fast-forward")


def _open_directory(path: Path) -> int:
    """Walk without symlinks; the caller must pre-provision a private directory."""
    _need(path.is_absolute() and ".." not in path.parts, "absolute non-traversing root required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        _need(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
              "private owned 0700 root required")
        result, fd = fd, -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def _file_metadata(fd: int) -> os.stat_result:
    info = os.fstat(fd)
    _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1
          and stat.S_IMODE(info.st_mode) == 0o600, "unsafe lock/journal metadata")
    return info



def _read_lock_fdinfo(fd: int) -> bytes:
    """Read this process's descriptor evidence, never an arbitrary proc path."""
    _need(type(fd) is int and fd >= 0, "owned lock descriptor required")
    handle = os.open(f"/proc/{os.getpid()}/fdinfo/{fd}",
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        data = bytearray()
        while len(data) <= 4096:
            chunk = os.read(handle, 4097 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        _need(0 < len(data) <= 4096, "lock fdinfo missing or oversized")
        return bytes(data)
    finally:
        os.close(handle)


def _verify_owned_flock(raw: bytes, metadata: os.stat_result, pid: int) -> None:
    """Linux fdinfo must report our exclusive whole-file open-description lock.

    This is a sampled cooperative check, not a history of continuous ownership
    or protection from malicious code sharing this process's descriptors.
    """
    _need(type(raw) is bytes and 0 < len(raw) <= 4096 and raw.endswith(b"\n"),
          "incomplete kernel lock evidence")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError:
        raise GuardBlocked("invalid kernel lock evidence") from None
    locks = [line for line in lines if line.startswith("lock:")]
    inodes = [line for line in lines if line.startswith("ino:")]
    _need(len(locks) == 1 and len(inodes) == 1, "own exclusive flock not observed")
    match = re.fullmatch(r"lock:\s+[0-9]+:\s+FLOCK\s+ADVISORY\s+WRITE\s+([0-9]+)\s+"
                         r"([0-9a-f]+):([0-9a-f]+):([0-9]+)\s+0\s+EOF", locks[0])
    inode = re.fullmatch(r"ino:\s+([0-9]+)", inodes[0])
    _need(match is not None and inode is not None, "exclusive whole-file flock required")
    owner, major, minor, locked_inode = match.groups()
    _need(int(owner) == pid and int(major, 16) == os.major(metadata.st_dev)
          and int(minor, 16) == os.minor(metadata.st_dev)
          and int(locked_inode) == metadata.st_ino == int(inode.group(1)),
          "kernel lock belongs to another owner or file")


def _require_owned_flock(fd: int) -> None:
    """Validate without reacquiring, upgrading, unlocking or writing the lock."""
    try:
        before = _file_metadata(fd)
        _need(before.st_size == 0, "empty private execution lock required")
        _verify_owned_flock(_read_lock_fdinfo(fd), before, os.getpid())
        after = _file_metadata(fd)
        _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
              == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
              "lock descriptor changed during kernel observation")
    except OSError:
        raise GuardBlocked("owned kernel lock evidence unavailable") from None


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        _need(key not in result, "duplicate journal field")
        result[key] = value
    return result


class ExecutionGuard:
    """A process-bound flock held continuously through observation and callback.

    Inspection of an uncertain intent is allowed under the lock. No API exists
    here for resolving a prior uncertain intent, deleting evidence or stealing
    ownership. Live installation and fixed operator integration are separate.
    """
    def __init__(self, directory: Path, *, run_id: str, invocation_type: str):
        _need(isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", run_id) is not None,
              "invalid run identity")
        _need(isinstance(invocation_type, str) and invocation_type in INVOCATIONS, "invalid invocation type")
        self.directory = Path(directory)
        self.run_id, self.invocation_type = run_id, invocation_type
        self._root = self._lock = self._journal = -1
        self._pid = 0
        self._used = False
        self._held = False

    def __enter__(self) -> ExecutionGuard:
        _need(not self._used, "guard instances cannot be reused")
        self._used = True
        try:
            self._root = _open_directory(self.directory)
            self._lock = os.open("execution.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=self._root)
            _file_metadata(self._lock)
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ConcurrentOwner("another executor owns the kernel lock") from None
            self._held = True
            self._pid = os.getpid()
            _require_owned_flock(self._lock)
            self._journal = os.open("effects.jsonl", os.O_RDWR | os.O_APPEND | os.O_CREAT
                                    | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._root)
            _file_metadata(self._journal)
            os.fsync(self._root)
            self._assert_held()
            self._records()
            return self
        except BaseException:
            self._close()
            raise

    def _assert_held(self) -> None:
        _need(self._held and self._pid == os.getpid(), "live process-bound ownership required")
        check = _open_directory(self.directory)
        try:
            _need(_identity(os.fstat(check)) == _identity(os.fstat(self._root)), "guard directory replaced")
        finally:
            os.close(check)
        for name, fd in (("execution.lock", self._lock), ("effects.jsonl", self._journal)):
            info = _file_metadata(fd)
            named = os.stat(name, dir_fd=self._root, follow_symlinks=False)
            _need(stat.S_ISREG(named.st_mode) and _identity(info) == _identity(named),
                  "lock/journal pathname replaced")
        _require_owned_flock(self._lock)

    def _records(self) -> list[dict]:
        self._assert_held()
        size = os.fstat(self._journal).st_size
        _need(size <= MAX_JOURNAL_BYTES, "journal bound exceeded; review required")
        raw = os.pread(self._journal, size + 1, 0)
        _need(len(raw) == size and (not raw or raw.endswith(b"\n")), "partial journal requires reconciliation")
        records: list[dict] = []
        previous = "0" * 64
        pending = None
        used_ids: set[str] = set()
        for number, line in enumerate(raw.splitlines(), 1):
            _need(0 < len(line) <= MAX_RECORD_BYTES, "invalid journal record size")
            try:
                item = json.loads(line, object_pairs_hook=_unique_pairs)
            except (ValueError, UnicodeError):
                raise GuardBlocked("malformed journal; no truncation permitted") from None
            _need(isinstance(item, dict) and set(item) == {"schema", "sequence", "previous", "at", "kind",
                  "task_id", "run_id", "invocation_type", "payload", "sha256"}, "invalid journal fields")
            body = {k: v for k, v in item.items() if k != "sha256"}
            _need(item["schema"] == SCHEMA and type(item["sequence"]) is int and item["sequence"] == number
                  and item["previous"] == previous and item["sha256"] == _digest(body), "journal chain differs")
            _need(item["task_id"] == TASK_ID and isinstance(item["invocation_type"], str) and item["invocation_type"] in INVOCATIONS
                  and isinstance(item["run_id"], str)
                  and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", item["run_id"]) is not None, "journal owner differs")
            try:
                at = datetime.fromisoformat(item["at"])
                _need(at.utcoffset() is not None and at.utcoffset().total_seconds() == 0,
                      "journal timestamp must be UTC")
            except (TypeError, ValueError):
                raise GuardBlocked("invalid journal timestamp") from None
            payload = item["payload"]
            _need(isinstance(payload, dict), "invalid journal payload")
            if item["kind"] == "intent":
                _need(pending is None and set(payload) == {"request_id", "action", "target_commit", "binding"},
                      "overlapping or invalid intent")
                _need(_uuid(payload["request_id"]) and payload["request_id"] not in used_ids
                      and isinstance(payload["action"], str) and payload["action"] in ACTIONS and _hex(payload["target_commit"], 40),
                      "invalid or reused effect identity")
                _action_binding(_binding(payload["binding"]), payload["action"], payload["target_commit"])
                pending = item
                used_ids.add(payload["request_id"])
            elif item["kind"] == "result":
                _need(pending is not None and set(payload) == {"intent_sha256", "outcome", "evidence_sha256"},
                      "unpaired or invalid result")
                _need(payload["intent_sha256"] == pending["sha256"]
                      and item["run_id"] == pending["run_id"]
                      and item["invocation_type"] == pending["invocation_type"], "result owner or intent differs")
                ObservedResult(payload["outcome"], payload["evidence_sha256"]).validate()
                pending = None
            else:
                raise GuardBlocked("unknown journal kind")
            records.append(item)
            previous = item["sha256"]
        return records

    def pending(self) -> dict | None:
        records = self._records()
        return records[-1] if records and records[-1]["kind"] == "intent" else None

    def _append(self, kind: str, payload: dict) -> dict:
        records = self._records()
        body = {"schema": SCHEMA, "sequence": len(records) + 1,
                "previous": records[-1]["sha256"] if records else "0" * 64,
                "at": datetime.now(timezone.utc).isoformat(), "kind": kind,
                "task_id": TASK_ID, "run_id": self.run_id,
                "invocation_type": self.invocation_type, "payload": payload}
        item = {**body, "sha256": _digest(body)}
        data = _canon(item) + b"\n"
        _need(len(data) <= MAX_RECORD_BYTES and os.fstat(self._journal).st_size + len(data) <= MAX_JOURNAL_BYTES,
              "journal capacity requires review")
        self._assert_held()
        remaining = memoryview(data)
        while remaining:
            self._assert_held()
            try:
                written = os.write(self._journal, remaining)
            except InterruptedError:
                continue
            _need(written > 0, "journal write made no progress")
            remaining = remaining[written:]
        self._assert_held()
        os.fsync(self._journal)
        os.fsync(self._root)
        _need(self._records()[-1] == item, "journal readback differs")
        return item

    def perform(self, *, action: str, target_commit: str, expected: Binding | SyncBinding,
                observe: Callable[[], Binding | SyncBinding], invoke: Callable[[], ObservedResult]) -> dict:
        """Run one already-authorized caller operation, never a prior intent.

        observe MUST read current clean-main/boot/closed-operation/generation from
        accepted project tooling, not from retained flags or invented snapshots.
        invoke MUST enforce every action-specific approval and evidence gate.
        Both callbacks run while this process owns the same nonblocking lock.
        """
        self._assert_held()
        _need(isinstance(action, str) and action in ACTIONS and _hex(target_commit, 40), "invalid effect request")
        _need(type(expected) in (Binding, SyncBinding), "typed expected context required")
        expected.validate()
        _action_binding(expected, action, target_commit)
        if self.pending() is not None:
            raise UncertainEffect("prior intent requires external evidence reconciliation, never replay")
        current = observe()
        _need(type(current) is type(expected) and current == expected, "current context differs before intent")
        current.validate()
        intent = self._append("intent", {"request_id": str(uuid4()), "action": action,
                              "target_commit": target_commit, "binding": asdict(expected)})
        self._assert_held()
        current = observe()
        _need(type(current) is type(expected) and current == expected, "context changed after intent; no effect attempted")
        current.validate()
        self._assert_held()
        result = invoke()
        _need(type(result) is ObservedResult, "callback outcome not established")
        result.validate()
        self._assert_held()
        return self._append("result", {"intent_sha256": intent["sha256"],
                                      "outcome": result.outcome, "evidence_sha256": result.evidence_sha256})

    def _close(self) -> None:
        # A forked child must not unlock the parent's shared open-file description.
        if self._held and self._pid == os.getpid() and self._lock >= 0:
            fcntl.flock(self._lock, fcntl.LOCK_UN)
        for field in ("_journal", "_lock", "_root"):
            fd = getattr(self, field)
            if fd >= 0:
                os.close(fd)
                setattr(self, field, -1)
        self._held = False

    def __exit__(self, *exc: object) -> None:
        self._close()
