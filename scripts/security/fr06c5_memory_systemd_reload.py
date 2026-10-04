"""FR-06C5E13 journal-bound systemd manager reload adapter.

This module supplies the missing `reload_units` production adapter.  It is
source-only: importing it performs no host action.  The concrete backend uses
an exact `systemctl daemon-reload` only when `apply()` is called under a
durable MemoryTransaction intent.  Tests inject a fake backend and never call
live systemd.

A daemon-reload has no inverse.  Rollback is therefore deliberately rejected;
after restoring unit files a *new* forward reload operation is required.  The
adapter never fabricates a before fingerprint to make rollback look reversible.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import UUID

from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
)

STEP = "reload_units"
UNIT_PATHS = {
    "aionex-fr06c5-encrypted-swap.service": "etc/systemd/system/aionex-fr06c5-encrypted-swap.service",
    "tmp.mount": "etc/systemd/system/tmp.mount",
}
MAX_BINDING = 65536


class ReloadStepRejected(RuntimeError):
    """Reload authority, identity or observable outcome is not acceptable."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _private_dir(path: Path) -> None:
    value = path.stat()
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        raise ReloadStepRejected("private owned state directory required")


def _file_identity(path: Path) -> dict[str, Any]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ReloadStepRejected("bound unit file unavailable") from exc
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o644
            or before.st_size <= 0
            or before.st_size > (1 << 20)
        ):
            raise ReloadStepRejected("unit file identity or mode rejected")
        data = bytearray()
        while len(data) <= (1 << 20):
            block = os.read(fd, min(8192, (1 << 20) + 1 - len(data)))
            if not block:
                break
            data.extend(block)
        after = os.fstat(fd)
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(data) != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in fields
        ):
            raise ReloadStepRejected("unit file changed while being identified")
        return {
            "dev": before.st_dev,
            "ino": before.st_ino,
            "mode": stat.S_IMODE(before.st_mode),
            "uid": before.st_uid,
            "gid": before.st_gid,
            "size": before.st_size,
            "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    finally:
        os.close(fd)


@dataclass(frozen=True)
class UnitState:
    name: str
    load_state: str
    fragment_path: str
    need_daemon_reload: bool


@dataclass(frozen=True)
class ManagerSnapshot:
    manager_need_daemon_reload: bool
    units: tuple[UnitState, ...]


class Manager(Protocol):
    def snapshot(self, units: tuple[str, ...]) -> ManagerSnapshot: ...

    def daemon_reload(self) -> None: ...


class SystemctlManager:
    """Narrow production backend; no shell and no implicit live invocation."""

    def __init__(
        self,
        *,
        executable: str = "/usr/bin/systemctl",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        if executable != "/usr/bin/systemctl":
            raise ReloadStepRejected("exact systemctl executable required")
        self.executable = executable
        self.runner = runner

    def _run(self, arguments: list[str]) -> str:
        result = self.runner(
            [self.executable, *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if (
            type(result.returncode) is not int
            or result.returncode != 0
            or not isinstance(result.stdout, str)
            or not isinstance(result.stderr, str)
            or result.stderr.strip()
        ):
            raise ReloadStepRejected("systemd manager command was not cleanly observed")
        return result.stdout

    @staticmethod
    def _properties(raw: str, required: set[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in raw.splitlines():
            if not line:
                continue
            if "=" not in line:
                raise ReloadStepRejected("malformed systemd property output")
            key, value = line.split("=", 1)
            if key in values:
                raise ReloadStepRejected("duplicate systemd property")
            values[key] = value
        if set(values) != required:
            raise ReloadStepRejected("incomplete systemd property output")
        return values

    @staticmethod
    def _bool(value: str) -> bool:
        if value == "yes":
            return True
        if value == "no":
            return False
        raise ReloadStepRejected("ambiguous systemd boolean")

    def snapshot(self, units: tuple[str, ...]) -> ManagerSnapshot:
        manager_raw = self._run(["show", "--property=NeedDaemonReload"])
        manager = self._properties(manager_raw, {"NeedDaemonReload"})
        observed: list[UnitState] = []
        for unit in units:
            raw = self._run(
                [
                    "show",
                    unit,
                    "--property=Id",
                    "--property=LoadState",
                    "--property=FragmentPath",
                    "--property=NeedDaemonReload",
                    "--no-pager",
                ]
            )
            item = self._properties(
                raw, {"Id", "LoadState", "FragmentPath", "NeedDaemonReload"}
            )
            if item["Id"] != unit:
                raise ReloadStepRejected("systemd unit identity changed")
            observed.append(
                UnitState(
                    name=unit,
                    load_state=item["LoadState"],
                    fragment_path=item["FragmentPath"],
                    need_daemon_reload=self._bool(item["NeedDaemonReload"]),
                )
            )
        return ManagerSnapshot(
            manager_need_daemon_reload=self._bool(manager["NeedDaemonReload"]),
            units=tuple(observed),
        )

    def daemon_reload(self) -> None:
        self._run(["daemon-reload"])


class SystemdReloadAdapter:
    """Exact-file, durable-intent adapter for the single `reload_units` step."""

    def __init__(
        self,
        *,
        root: Path,
        state_parent: Path,
        operation: str,
        context: Callable[[], BoundContext],
        manager: Manager | None = None,
    ):
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise ReloadStepRejected("canonical operation required")
        if not root.is_absolute() or not state_parent.is_absolute():
            raise ReloadStepRejected("absolute root and state parent required")
        _private_dir(state_parent)
        self.root = root
        self.state_parent = state_parent
        self.operation = operation
        self.read_context = context
        self.manager = manager or SystemctlManager()
        self.bundle = state_parent / ("reload-" + operation)
        self.journal: Journal | None = None
        self.binding: dict[str, Any] | None = None
        self.bound: BoundContext | None = None
        self.step: BoundStep | None = None

    @classmethod
    def prepare(
        cls,
        *,
        root: Path,
        state_parent: Path,
        operation: str,
        context: Callable[[], BoundContext],
        manager: Manager | None = None,
    ) -> Self:
        adapter = cls(
            root=root,
            state_parent=state_parent,
            operation=operation,
            context=context,
            manager=manager,
        )
        bound = context()
        if not isinstance(bound, BoundContext):
            raise ReloadStepRejected("typed bound context required")
        units = adapter._unit_identities()
        before = adapter._fingerprint("before", units)
        after = adapter._fingerprint("after", units)
        step = BoundStep(STEP, before, after)
        snapshot = adapter.manager.snapshot(tuple(UNIT_PATHS))
        if adapter._classify(snapshot, units) != "before":
            raise ReloadStepRejected("manager is not at exact pre-reload state")
        try:
            adapter.bundle.mkdir(mode=0o700)
        except OSError as exc:
            raise ReloadStepRejected("reload binding already exists or cannot be created") from exc
        body = {
            "schema": 1,
            "operation": operation,
            "context": asdict(bound),
            "root": str(root),
            "units": units,
            "step": asdict(step),
            "no_inverse": True,
        }
        adapter._write_new("binding.json", body)
        adapter._load_binding()
        return adapter

    @classmethod
    def load(
        cls,
        *,
        root: Path,
        state_parent: Path,
        operation: str,
        context: Callable[[], BoundContext],
        manager: Manager | None = None,
    ) -> Self:
        adapter = cls(
            root=root,
            state_parent=state_parent,
            operation=operation,
            context=context,
            manager=manager,
        )
        adapter._load_binding()
        return adapter

    def _write_new(self, name: str, value: dict[str, Any]) -> None:
        data = _canonical(value) + b"\n"
        if len(data) > MAX_BINDING:
            raise ReloadStepRejected("binding record exceeds bound")
        fd = os.open(
            self.bundle / name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            position = 0
            while position < len(data):
                count = os.write(fd, data[position:])
                if count <= 0:
                    raise OSError("binding write made no progress")
                position += count
            os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(
            self.bundle, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _load_binding(self) -> None:
        _private_dir(self.bundle)
        path = self.bundle / "binding.json"
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ReloadStepRejected("reload binding unavailable") from exc
        if not raw.endswith(b"\n") or not 0 < len(raw) <= MAX_BINDING:
            raise ReloadStepRejected("reload binding incomplete")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReloadStepRejected("reload binding invalid") from exc
        required = {
            "schema",
            "operation",
            "context",
            "root",
            "units",
            "step",
            "no_inverse",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ReloadStepRejected("reload binding fields differ")
        if (
            value["schema"] != 1
            or value["operation"] != self.operation
            or value["root"] != str(self.root)
            or value["no_inverse"] is not True
        ):
            raise ReloadStepRejected("reload binding identity differs")
        bound = BoundContext(**value["context"])
        step = BoundStep(**value["step"])
        if step.name != STEP:
            raise ReloadStepRejected("reload binding step differs")
        if value["units"] != self._unit_identities():
            raise ReloadStepRejected("bound unit file identity changed")
        if step.before_sha256 != self._fingerprint("before", value["units"]):
            raise ReloadStepRejected("bound before fingerprint differs")
        if step.after_sha256 != self._fingerprint("after", value["units"]):
            raise ReloadStepRejected("bound after fingerprint differs")
        self.binding = value
        self.bound = bound
        self.step = step

    def _unit_identities(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name, relative in UNIT_PATHS.items():
            path = self.root / relative
            identity = _file_identity(path)
            result[name] = {
                "relative": relative,
                "absolute": str(path),
                "identity": identity,
            }
        return result

    def _fingerprint(self, state: str, units: dict[str, Any]) -> str:
        if state not in {"before", "after"}:
            raise ReloadStepRejected("unknown reload state")
        return _digest(
            {
                "schema": 1,
                "operation": self.operation,
                "step": STEP,
                "state": state,
                "units": units,
            }
        )

    def _classify(
        self, snapshot: ManagerSnapshot, units: dict[str, Any]
    ) -> str | None:
        if not isinstance(snapshot, ManagerSnapshot):
            return None
        expected_names = tuple(UNIT_PATHS)
        if tuple(item.name for item in snapshot.units) != expected_names:
            return None
        if snapshot.manager_need_daemon_reload:
            return "before"
        for item in snapshot.units:
            expected_path = units[item.name]["absolute"]
            if (
                item.load_state != "loaded"
                or item.fragment_path != expected_path
                or item.need_daemon_reload
            ):
                return None
        return "after"

    def context(self) -> BoundContext:
        if self.bound is None:
            raise ReloadStepRejected("reload binding not loaded")
        current = self.read_context()
        if not isinstance(current, BoundContext) or current != self.bound:
            raise ReloadStepRejected("independent bound context changed")
        return current

    def attach(self, journal: Journal) -> None:
        if self.bound is None or self.step is None:
            raise ReloadStepRejected("reload binding not loaded")
        if (
            journal.plan.operation != self.operation
            or journal.plan.context != self.bound
            or journal.plan.steps != (self.step,)
        ):
            raise ReloadStepRejected("exact single-step reload journal required")
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        if self.binding is None or self.step is None:
            raise ReloadStepRejected("reload binding not loaded")
        if step != self.step or operation != self.operation:
            raise ReloadStepRejected("foreign reload operation")
        units = self._unit_identities()
        if units != self.binding["units"]:
            raise ReloadStepRejected("unit files changed after binding")
        snapshot = self.manager.snapshot(tuple(UNIT_PATHS))
        state = self._classify(snapshot, units)
        if state is None:
            return Observation("0" * 64, False, False)
        fingerprint = self._fingerprint(state, units)
        owned = False
        if state == "after" and self.journal is not None:
            journal_state = self.journal.state()
            owned = (
                journal_state.applied == 1
                or journal_state.pending == ("apply", 0)
            )
        return Observation(fingerprint, True, owned)

    def apply(self, step: BoundStep, operation: str) -> None:
        if self.journal is None or self.step is None:
            raise ReloadStepRejected("attached durable journal required")
        if step != self.step or operation != self.operation:
            raise ReloadStepRejected("foreign reload operation")
        state = self.journal.state()
        if state.pending != ("apply", 0):
            raise ReloadStepRejected("durable apply intent required")
        before = self.observe(step, operation)
        if not before.identity_verified or before.fingerprint != step.before_sha256:
            raise ReloadStepRejected("exact pre-reload state changed")
        self.context()
        self.manager.daemon_reload()
        self.context()
        after = self.observe(step, operation)
        if (
            not after.identity_verified
            or not after.owned_by_operation
            or after.fingerprint != step.after_sha256
        ):
            raise ReloadStepRejected("daemon-reload postcondition not independently observed")

    def undo(self, step: BoundStep, operation: str) -> None:
        if self.journal is None or self.step is None:
            raise ReloadStepRejected("attached durable journal required")
        if step != self.step or operation != self.operation:
            raise ReloadStepRejected("foreign reload operation")
        if self.journal.state().pending != ("undo", 0):
            raise ReloadStepRejected("durable undo intent required")
        raise ReloadStepRejected(
            "daemon-reload has no inverse; restore unit files and use a new forward reload operation"
        )
