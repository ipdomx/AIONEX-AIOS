"""C5E3 file-step adapter for the C5E2 intent journal, not a host activator.

This implements only unit-file installation and the exact legacy fstab edit.
All effects are real Linux descriptor-relative renameat2 operations; there is no
swap, mapper, mount, systemctl, credential/bootstrap or production CLI here.
A caller must supply a fresh, independently attested closed/writer-frozen context.
The file lock serializes cooperating adapters, not an administrator or a live
noncooperating writer. These primitives do not authorize production activation.

An existing fstab inode is exchanged with the staged inode, never overwritten
or unlinked. Restoration exchanges it back. Newly installed units move back to
private staging on undo. Both directories are fsynced before returning. Unknown
ownership, name replacement, partial staging or missing evidence stop effects.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from scripts.security.fr06c5_memory_transaction import (
    BoundContext,
    BoundStep,
    Journal,
    Observation,
    TransitionRejected,
)

TARGETS = {
    "install_swap_unit": "etc/systemd/system/aionex-fr06c5-encrypted-swap.service",
    "install_tmp_unit": "etc/systemd/system/tmp.mount",
    "disable_legacy_fstab": "etc/fstab",
}
MAX_FILE = 65536
NOREPLACE = 1
EXCHANGE = 2


class FileStepRejected(TransitionRejected):
    """No effect is permitted with incomplete file identity or ownership proof."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FileStepRejected("Duplicate manifest key")
        result[key] = value
    return result


def _open_dir(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise FileStepRejected("Absolute, non-traversing directory required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                          dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _dir_identity(fd: int, *, private: bool = False) -> dict[str, int]:
    s = os.fstat(fd)
    mode = stat.S_IMODE(s.st_mode)
    if (not stat.S_ISDIR(s.st_mode) or s.st_uid != os.geteuid()
            or mode & 0o022 or (private and mode != 0o700)):
        raise FileStepRejected("Directory is not owned or sufficiently private")
    return {"device": s.st_dev, "inode": s.st_ino, "uid": s.st_uid, "gid": s.st_gid, "mode": mode}


def _file(parent: int, name: str, *, private: bool = False) -> tuple[dict[str, Any] | None, bytes]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    except FileNotFoundError:
        return None, b""
    try:
        before = os.fstat(fd)
        mode = stat.S_IMODE(before.st_mode)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.geteuid() or mode & 0o7133
                or (private and mode != 0o600) or not 0 < before.st_size <= MAX_FILE):
            raise FileStepRejected("File is not a bounded owned regular file")
        if os.listxattr(fd):
            raise FileStepRejected("Extended attributes need an independently reviewed preservation contract")
        content = bytearray()
        while len(content) <= MAX_FILE:
            block = os.read(fd, min(8192, MAX_FILE + 1 - len(content)))
            if not block:
                break
            content.extend(block)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        stable = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(content) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in stable)
                or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)):
            raise FileStepRejected("File changed while being observed")
        # rename changes ctime; read changes atime. Neither belongs in the
        # planned stable fingerprint, but ctime is checked across each read.
        info = {"device": after.st_dev, "inode": after.st_ino, "uid": after.st_uid,
                "gid": after.st_gid, "mode": mode, "links": after.st_nlink,
                "size": after.st_size, "mtime_ns": after.st_mtime_ns,
                "sha256": hashlib.sha256(content).hexdigest()}
        return info, bytes(content)
    finally:
        os.close(fd)


def _write_new(parent: int, name: str, content: bytes, mode: int, gid: int | None = None) -> None:
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_FILE:
        raise FileStepRejected("Bounded nonempty bytes required")
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=parent)
    try:
        position = 0
        while position < len(content):
            written = os.write(fd, content[position:])
            if written <= 0:
                raise OSError("File write made no progress")
            position += written
        if gid is not None:
            os.fchown(fd, -1, gid)
        os.fchmod(fd, mode)
        os.fsync(fd)
        os.fsync(parent)
    finally:
        os.close(fd)


def disable_legacy_fstab(content: bytes, operation: str) -> bytes:
    """Change one exact plaintext swap entry, retaining every unrelated byte.

    No decoded/escaped path guesses, duplicate entries, other swaps or prior
    marker are accepted. UUID or encoded alias handling needs a separate review.
    """
    if str(UUID(operation)) != operation or not isinstance(content, bytes):
        raise FileStepRejected("Exact operation and bytes required")
    if not content or len(content) > MAX_FILE or b"\0" in content or b"\r" in content:
        raise FileStepRejected("Unsupported fstab encoding or size")
    marker = b"# AIONEX_C5E3_DISABLED "
    if marker in content:
        raise FileStepRejected("Prior memory-control marker exists")
    lines = content.splitlines(keepends=True)
    found = []
    for index, line in enumerate(lines):
        active = line.split(b"#", 1)[0].strip()
        if not active:
            continue
        fields = active.split()
        if len(fields) != 6 or any(b"\\" in v for v in fields):
            raise FileStepRejected("Ambiguous or escaped fstab entry")
        if fields[2] == b"swap" or fields[0] == b"/swap.img":
            if (fields[0] != b"/swap.img" or fields[1] not in {b"none", b"swap"}
                    or fields[2] != b"swap" or fields[4:] != [b"0", b"0"]):
                raise FileStepRejected("Unexpected legacy or additional swap entry")
            found.append(index)
    if len(found) != 1:
        raise FileStepRejected("Exactly one plain legacy swap entry required")
    index = found[0]
    lines[index] = marker + operation.encode("ascii") + b" " + lines[index]
    result = b"".join(lines)
    if len(result) > MAX_FILE:
        raise FileStepRejected("Rewritten fstab exceeds bound")
    return result


def rename_owned(source_fd: int, source: str, dest_fd: int, dest: str, *, exchange: bool) -> None:
    """One Linux atomic rename, without a copy/unlink or overwrite fallback."""
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    if function is None:
        raise FileStepRejected("renameat2 unavailable; no weaker fallback")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    result = function(source_fd, os.fsencode(source), dest_fd, os.fsencode(dest), EXCHANGE if exchange else NOREPLACE)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, "Owned file rename did not complete")


class ConfigFileAdapter:
    """Three journal-bound filesystem steps; all kernel/service steps rejected.

    Staging is private, create-only and on each target's own filesystem. The
    immutable manifest binds both original and candidate inodes. It must be
    retained with the journal for reconciliation. No staging cleanup API exists.
    Unknown intermediate outcomes must not be erased to manufacture a retry.
    """
    def __init__(self, root: Path, state_parent: Path, operation: str,
                 context: Callable[[], BoundContext]):
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise FileStepRejected("Canonical operation required")
        self.root, self.state_parent, self.operation = root, state_parent, operation
        self._read_context = context
        self.root_fd = self.state_fd = self.lock_fd = self.bundle_fd = -1
        self.parents: dict[str, int] = {}
        self.stages: dict[str, int] = {}
        self.journal: Journal | None = None
        try:
            self.root_fd = _open_dir(root)
            self.state_fd = _open_dir(state_parent)
            self.root_identity = _dir_identity(self.root_fd)
            self.state_identity = _dir_identity(self.state_fd, private=True)
            self.lock_fd = os.open(".config.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                   0o600, dir_fd=self.state_fd)
            lock = os.fstat(self.lock_fd)
            if (not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.geteuid()
                    or stat.S_IMODE(lock.st_mode) != 0o600 or lock.st_nlink != 1 or lock.st_size):
                raise FileStepRejected("Invalid configuration lock")
            self.lock_identity = (lock.st_dev, lock.st_ino)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.lock_fd)
            os.fsync(self.state_fd)
        except BaseException:
            self.close()
            raise

    @classmethod
    def prepare(cls, root: Path, state_parent: Path, operation: str,
                context: Callable[[], BoundContext], units: Mapping[str, bytes]) -> Self:
        if set(units) != {"install_swap_unit", "install_tmp_unit"}:
            raise FileStepRejected("Only the two explicitly reviewed unit files are allowed")
        adapter = cls(root, state_parent, operation, context)
        try:
            bound = context()
            if not isinstance(bound, BoundContext):
                raise FileStepRejected("Independent typed context is required")
            os.mkdir(operation, mode=0o700, dir_fd=adapter.state_fd)
            os.fsync(adapter.state_fd)
            adapter.bundle_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=adapter.state_fd)
            spec: dict[str, Any] = {"schema": 1, "operation": operation, "context": asdict(bound),
                                    "root": adapter.root_identity, "state": adapter.state_identity,
                                    "bundle": _dir_identity(adapter.bundle_fd, private=True),
                                    "lock": list(adapter.lock_identity), "files": {}}
            for index, (step, relative) in enumerate(TARGETS.items()):
                parent = _open_dir(root / Path(relative).parent)
                adapter.parents[step] = parent
                parent_info = _dir_identity(parent)
                name = Path(relative).name
                before, source = _file(parent, name)
                if step == "disable_legacy_fstab":
                    if before is None:
                        raise FileStepRejected("Original fstab must exist")
                    content = disable_legacy_fstab(source, operation)
                else:
                    if before is not None:
                        raise FileStepRejected("Pre-existing unit must not be replaced")
                    content = units[step]
                stage_name = f".aionex-memory-{operation}-{index}"
                os.mkdir(stage_name, mode=0o700, dir_fd=parent)
                os.fsync(parent)
                stage = os.open(stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                adapter.stages[step] = stage
                _write_new(stage, "candidate", content, before["mode"] if before else 0o644,
                           before["gid"] if before else None)
                candidate, _ = _file(stage, "candidate")
                spec["files"][step] = {"relative": relative, "name": name, "parent": parent_info,
                                       "stage_name": stage_name, "stage": _dir_identity(stage, private=True),
                                       "original": before, "candidate": candidate}
            if context() != bound:
                raise FileStepRejected("Context changed during staging; staging retained")
            _write_new(adapter.bundle_fd, "manifest.json", _canonical(spec) + b"\n", 0o600)
            adapter._load_spec()
            for bound_step in adapter.steps:
                if adapter.observe(bound_step, operation).fingerprint != bound_step.before_sha256:
                    raise FileStepRejected("Baseline changed during staging")
            return adapter
        except BaseException:
            adapter.close()
            raise

    @classmethod
    def load(cls, root: Path, state_parent: Path, operation: str,
             context: Callable[[], BoundContext]) -> Self:
        adapter = cls(root, state_parent, operation, context)
        try:
            adapter.bundle_fd = os.open(operation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=adapter.state_fd)
            adapter._load_spec()
            for step, spec in adapter.spec["files"].items():
                parent = _open_dir(root / Path(spec["relative"]).parent)
                adapter.parents[step] = parent
                adapter.stages[step] = os.open(spec["stage_name"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                              dir_fd=parent)
            adapter._identity()
            return adapter
        except BaseException:
            adapter.close()
            raise

    def _load_spec(self) -> None:
        self.manifest_identity, raw = _file(self.bundle_fd, "manifest.json", private=True)
        spec = json.loads(raw, object_pairs_hook=_unique)
        if (not isinstance(spec, dict) or set(spec) != {"schema", "operation", "context", "root", "state", "bundle", "lock", "files"}
                or type(spec["schema"]) is not int or spec["schema"] != 1 or spec["operation"] != self.operation
                or spec["root"] != self.root_identity or spec["state"] != self.state_identity
                or spec["lock"] != list(self.lock_identity)
                or spec["bundle"] != _dir_identity(self.bundle_fd, private=True)
                or not isinstance(spec["files"], dict) or set(spec["files"]) != set(TARGETS)):
            raise FileStepRejected("Configuration manifest does not match the pinned operation")
        self.bound_context = BoundContext(**spec["context"])
        for index, (step, relative) in enumerate(TARGETS.items()):
            item = spec["files"][step]
            if (not isinstance(item, dict) or set(item) != {"relative", "name", "parent", "stage_name", "stage", "original", "candidate"}
                    or item["relative"] != relative or item["name"] != Path(relative).name
                    or item["stage_name"] != f".aionex-memory-{self.operation}-{index}"
                    or (step == "disable_legacy_fstab") != (item["original"] is not None)
                    or not isinstance(item["candidate"], dict)):
                raise FileStepRejected("Unexpected configuration target")
        self.spec = spec
        self.spec_digest = hashlib.sha256(raw).hexdigest()
        self.steps = tuple(BoundStep(name, _digest(self._expected(name, False)), _digest(self._expected(name, True)))
                           for name in TARGETS)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        for store in (self.stages, self.parents):
            for fd in store.values():
                os.close(fd)
            store.clear()
        for attr in ("bundle_fd", "lock_fd", "state_fd", "root_fd"):
            fd = getattr(self, attr)
            if fd >= 0:
                os.close(fd)
                setattr(self, attr, -1)

    def _identity(self) -> None:
        if self.root_fd < 0 or self.lock_fd < 0:
            raise FileStepRejected("Closed file adapter")
        for path, expected, private in ((self.root, self.root_identity, False), (self.state_parent, self.state_identity, True)):
            fd = _open_dir(path)
            try:
                if _dir_identity(fd, private=private) != expected:
                    raise FileStepRejected("Pinned directory changed")
            finally:
                os.close(fd)
        lock = os.stat(".config.lock", dir_fd=self.state_fd, follow_symlinks=False)
        if ((lock.st_dev, lock.st_ino) != self.lock_identity or lock.st_nlink != 1
                or lock.st_uid != os.geteuid() or stat.S_IMODE(lock.st_mode) != 0o600 or lock.st_size):
            raise FileStepRejected("Configuration lock changed")
        bundle = os.stat(self.operation, dir_fd=self.state_fd, follow_symlinks=False)
        if ((bundle.st_dev, bundle.st_ino) != (self.spec["bundle"]["device"], self.spec["bundle"]["inode"])
                or not stat.S_ISDIR(bundle.st_mode) or _dir_identity(self.bundle_fd, private=True) != self.spec["bundle"]):
            raise FileStepRejected("Configuration bundle changed")
        manifest, raw = _file(self.bundle_fd, "manifest.json", private=True)
        if (manifest != self.manifest_identity or hashlib.sha256(raw).hexdigest() != self.spec_digest
                or os.listdir(self.bundle_fd) != ["manifest.json"]):
            raise FileStepRejected("Configuration manifest changed or incomplete")
        for step, spec in self.spec["files"].items():
            parent = self.parents[step]
            reopened = _open_dir(self.root / Path(spec["relative"]).parent)
            try:
                if _dir_identity(reopened) != spec["parent"] or _dir_identity(parent) != spec["parent"]:
                    raise FileStepRejected("Configuration parent changed")
            finally:
                os.close(reopened)
            named = os.stat(spec["stage_name"], dir_fd=parent, follow_symlinks=False)
            stage = self.stages[step]
            if (not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != (spec["stage"]["device"], spec["stage"]["inode"])
                    or _dir_identity(stage, private=True) != spec["stage"]
                    or not set(os.listdir(stage)).issubset({"candidate"})):
                raise FileStepRejected("Private staging identity or contents changed")

    def _expected(self, step: str, after: bool) -> dict[str, Any]:
        spec = self.spec["files"][step]
        return {"operation": self.operation, "root": self.spec["root"], "parent": spec["parent"], "stage": spec["stage"],
                "target": spec["candidate"] if after else spec["original"],
                "staged": spec["original"] if after else spec["candidate"]}

    def context(self) -> BoundContext:
        self._identity()
        context = self._read_context()
        if not isinstance(context, BoundContext) or context != self.bound_context:
            raise FileStepRejected("Independent bound context changed or unavailable")
        return context

    def attach(self, journal: Journal) -> None:
        if journal.plan.operation != self.operation or journal.plan.context != self.bound_context:
            raise FileStepRejected("Journal binding differs")
        if tuple(s for s in journal.plan.steps if s.name in TARGETS) != self.steps:
            raise FileStepRejected("Journal file fingerprints differ")
        self.journal = journal

    def observe(self, step: BoundStep, operation: str) -> Observation:
        self._identity()
        if operation != self.operation or step not in self.steps:
            raise FileStepRejected("Unknown operation or file step")
        item = self.spec["files"][step.name]
        target, _ = _file(self.parents[step.name], item["name"])
        candidate, _ = _file(self.stages[step.name], "candidate")
        actual = {**self._expected(step.name, False), "target": target, "staged": candidate}
        self._identity()
        fingerprint = _digest(actual)
        recognized = fingerprint in {step.before_sha256, step.after_sha256}
        return Observation(fingerprint, recognized, recognized and fingerprint == step.after_sha256)

    def _perform(self, step: BoundStep, operation: str, *, undo: bool) -> None:
        self.context()
        if self.journal is None:
            raise FileStepRejected("A durable pending journal intent is required")
        state = self.journal.state()
        direction = "undo" if undo else "apply"
        if (state.pending is None or state.pending[0] != direction
                or self.journal.plan.steps[state.pending[1]] != step or operation != self.operation):
            raise FileStepRejected("Exact durable intent not found")
        observation = self.observe(step, operation)
        expected = step.after_sha256 if undo else step.before_sha256
        if not observation.identity_verified or observation.fingerprint != expected or (undo and not observation.owned_by_operation):
            raise FileStepRejected("Source or rollback resource is not exactly owned")
        # A prior file can change after its own settlement. Never proceed with
        # the next file while any earlier/remaining resource has drifted.
        for bound_step in self.steps:
            index = self.journal.plan.steps.index(bound_step)
            already_applied = index < state.applied
            proof = self.observe(bound_step, operation)
            fingerprint = bound_step.after_sha256 if already_applied else bound_step.before_sha256
            if (not proof.identity_verified or proof.fingerprint != fingerprint
                    or (already_applied and not proof.owned_by_operation)):
                raise FileStepRejected("Another bound file drifted before this effect")
        self.context()
        item = self.spec["files"][step.name]
        parent, stage = self.parents[step.name], self.stages[step.name]
        if item["original"] is not None:
            rename_owned(stage, "candidate", parent, item["name"], exchange=True)
        elif undo:
            rename_owned(parent, item["name"], stage, "candidate", exchange=False)
        else:
            rename_owned(stage, "candidate", parent, item["name"], exchange=False)
        os.fsync(stage)
        os.fsync(parent)
        self._identity()

    def apply(self, step: BoundStep, operation: str) -> None:
        self._perform(step, operation, undo=False)

    def undo(self, step: BoundStep, operation: str) -> None:
        self._perform(step, operation, undo=True)
