"""Joined, durably owned resources for an admitted Security Lab execution.

Only the worker binds a runtime. Cancellation never discards a running thread,
process spawn, pipe drain or cleanup operation. Unknown observations leave the
persistent registry unresolved instead of declaring the host drained.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, TypeVar

from app.db.base import SessionLocal
from app.services import host_maintenance_scan_execution as registry
from app.services.host_maintenance_admission import SessionFactory

T = TypeVar("T")
_CURRENT: ContextVar[ScanResourceRuntime | None] = ContextVar("scan_resource_runtime", default=None)


def current_runtime() -> ScanResourceRuntime | None:
    return _CURRENT.get()


def require_runtime(scan_id: str) -> ScanResourceRuntime:
    runtime = current_runtime()
    if runtime is None or runtime.owner.scan_id != scan_id:
        raise registry.ScanExecutionOwnershipLost("A scan requires its admitted resource runtime")
    runtime.entered = True
    return runtime


async def join_task(task: asyncio.Future[T]) -> tuple[T, bool]:
    """Join an already-created task without propagating repeated caller cancels.

    The cancellation flag must be handled by the caller AFTER it records the
    outcome. This also handles cancellation while acquiring a process handle.
    """
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            if not task.done():
                raise
    return task.result(), cancelled


async def finish(awaitable: Awaitable[T]) -> T:
    """Cleanup-only join; callers retain and re-raise their original exception."""
    value, _ = await join_task(asyncio.ensure_future(awaitable))
    return value


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


def _proc_stat(pid: int) -> tuple[int, int, int]:
    # comm is parenthesized and may itself contain spaces or ')'.
    raw = Path(f"/proc/{pid}/stat").read_text()
    tail = raw[raw.rfind(")") + 2:].split()
    if len(tail) < 20:
        raise registry.ScanExecutionUncertain("Process identity is incomplete")
    return int(tail[2]), int(tail[3]), int(tail[19])  # pgrp, session, starttime




class ScanResourceRuntime:
    def __init__(
        self, owner: registry.ScanExecutionOwnership,
        *, session_factory: SessionFactory = SessionLocal,
    ) -> None:
        self.owner = owner
        self.sessions = session_factory
        self.entered = False
        self.cancel_requested = False
        self.supervision_failed = False
        self.workspace: Path | None = None

    @contextmanager
    def bind(self) -> Iterator[ScanResourceRuntime]:
        binding = _CURRENT.set(self)
        try:
            yield self
        finally:
            _CURRENT.reset(binding)

    async def checkpoint(self) -> None:
        if self.supervision_failed:
            raise registry.ScanExecutionUncertain("Execution supervision failed")
        if self.cancel_requested:
            raise registry.ScanExecutionCancelled()
        if await registry.heartbeat_execution(self.owner, session_factory=self.sessions):
            self.cancel_requested = True
            raise registry.ScanExecutionCancelled()

    async def reserve(self, kind: str, operation: str, **kwargs: Any) -> str:
        await self.checkpoint()
        return await registry.reserve_resource(
            self.owner, kind, identity={"operation": operation},
            session_factory=self.sessions, **kwargs,
        )

    async def update(self, identifier: str, **kwargs: Any) -> None:
        await registry.update_resource(
            self.owner, identifier, session_factory=self.sessions, **kwargs,
        )

    async def uncertain(self, identifier: str, exc: BaseException) -> None:
        await self.update(identifier, state="unresolved", evidence={"error_type": type(exc).__name__})

    async def thread(self, operation: str, function: Callable[..., T], *args: Any) -> T:
        identifier = await self.reserve("thread", operation)
        await self.update(identifier, state="active")
        # Creation is synchronous; there is no cancellable await between creating
        # the task and entering the protected join. The executor future is never
        # cancelled, so a completed asyncio wrapper means the callable returned.
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        cancelled = False
        error: BaseException | None = None
        value: T
        try:
            value, cancelled = await join_task(task)
        except BaseException as exc:
            error = exc
        finally:
            await finish(self.update(identifier, state="settled", evidence={
                "joined": True, "cleanup_complete": True,
            }))
        if error is not None:
            raise error
        if cancelled:
            raise asyncio.CancelledError()
        return value

    async def async_io(self, operation: str, factory: Callable[[], Awaitable[T]]) -> T:
        identifier = await self.reserve("async_io", operation)
        await self.update(identifier, state="active")
        # Do not cancel the I/O coroutine: join its own bounded request and
        # context-manager cleanup. An internal timeout/error is conservatively
        # unresolved because an underlying DNS/transport worker may be unknown.
        task = asyncio.ensure_future(factory())
        try:
            value, cancelled = await join_task(task)
        except BaseException as exc:
            await finish(self.uncertain(identifier, exc))
            raise
        await finish(self.update(identifier, state="settled", evidence={
            "joined": True, "cleanup_complete": True,
        }))
        if cancelled:
            raise asyncio.CancelledError()
        return value

    @asynccontextmanager
    async def temporary_workspace(self, operation: str) -> AsyncIterator[Path]:
        identifier = await self.reserve("async_io", operation)
        directory: tempfile.TemporaryDirectory[str] | None = None
        previous = self.workspace
        try:
            directory = tempfile.TemporaryDirectory(prefix="aionex-scan-", dir="/tmp")
            self.workspace = Path(directory.name)
            await self.update(identifier, state="active")
            yield self.workspace
        finally:
            self.workspace = previous
            if directory is not None:
                try:
                    # Cleanup is joined even under repeated cancellation. A
                    # failure is preserved, never replaced with missing_ok=True.
                    await finish(asyncio.to_thread(directory.cleanup))
                    await finish(self.update(identifier, state="settled", evidence={
                        "joined": True, "cleanup_complete": True,
                    }))
                except BaseException as exc:
                    await finish(self.uncertain(identifier, exc))
                    raise

    async def process(self, command: list[str], *, timeout: float) -> ProcessResult:
        identifier = await self.reserve("process", "fixed-scanner-adapter")
        process: asyncio.subprocess.Process | None = None
        capture: asyncio.Task[tuple[bytes, bytes]] | None = None
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        timed_out = False
        cancelled = False
        failure: BaseException | None = None
        output: tuple[bytes, bytes] = (b"", b"")
        proof: dict[str, Any] = {}
        ready = False

        async def readiness() -> None:
            nonlocal ready
            data = b""
            async with asyncio.timeout(5):
                while len(data) < 6:
                    try:
                        chunk = os.read(read_fd, 6 - len(data))
                    except BlockingIOError:
                        await asyncio.sleep(0.01)
                        continue
                    if not chunk:
                        raise registry.ScanExecutionUncertain("Child supervisor did not initialize")
                    data += chunk
            if data != b"READY\n":
                raise registry.ScanExecutionUncertain("Invalid child supervisor handshake")
            ready = True

        try:
            env = {**os.environ, "NO_COLOR": "1"}
            if self.workspace is not None:
                env.update(HOME=str(self.workspace), TMPDIR=str(self.workspace),
                           XDG_CACHE_HOME=str(self.workspace / "cache"))
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).with_name("security_scan_process_entry.py")),
                str(write_fd), *command, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True, pass_fds=(write_fd,), env=env,
                cwd=str(self.workspace) if self.workspace is not None else None,
            ))
            spawned, cancelled = await join_task(spawn)
            process = spawned
            os.close(write_fd)
            write_fd = -1
            _, interrupted = await join_task(asyncio.create_task(readiness()))
            cancelled = cancelled or interrupted
            pgid, sid, ticks = _proc_stat(spawned.pid)
            if pgid != spawned.pid or sid != spawned.pid or ticks <= 0:
                raise registry.ScanExecutionUncertain("Supervisor identity is invalid")
            await self.update(identifier, state="active", identity={
                "pid": spawned.pid, "pgid": pgid, "sid": sid,
                "start_ticks": ticks, "boot_id": boot,
            })
            if cancelled:
                raise asyncio.CancelledError()
            await self.checkpoint()
            assert spawned.stdin is not None
            spawned.stdin.write(b"1")
            await spawned.stdin.drain()
            capture = asyncio.create_task(spawned.communicate())
            output = await asyncio.wait_for(asyncio.shield(capture), timeout=timeout)
        except TimeoutError as exc:
            timed_out = True
            failure = exc
        except BaseException as exc:
            failure = exc
        finally:
            try:
                if process is not None:
                    async def cleanup() -> None:
                        nonlocal output, capture, proof
                        assert process is not None
                        if process.stdin is not None:
                            process.stdin.close()
                        if process.returncode is None and ready:
                            # Ask only the owned supervisor to reap its children.
                            # Never send signals to a guessed global PID/group.
                            try:
                                process.terminate()
                            except ProcessLookupError:
                                pass
                        if capture is None:
                            capture = asyncio.create_task(process.communicate())
                        try:
                            output = await asyncio.wait_for(asyncio.shield(capture), timeout=10)
                            await asyncio.wait_for(process.wait(), timeout=5)
                        except BaseException:
                            capture.cancel()
                            await asyncio.gather(capture, return_exceptions=True)
                            raise
                        if process.returncode != 0 or not ready:
                            raise registry.ScanExecutionUncertain("Child supervisor did not prove cleanup")
                        if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != boot:
                            raise registry.ScanExecutionUncertain("Process boot identity changed")
                        data = os.read(read_fd, 4096)
                        if not data or len(data) >= 4096:
                            raise registry.ScanExecutionUncertain("Child cleanup proof is absent")
                        proof = json.loads(data)
                        if (not isinstance(proof, dict) or set(proof) != {
                            "version", "subreaper", "children_reaped", "exit_code", "started",
                        } or type(proof["version"]) is not int or proof["version"] != 1
                                or proof["subreaper"] is not True
                                or proof["children_reaped"] is not True
                                or type(proof["exit_code"]) is not int
                                or type(proof["started"]) is not bool):
                            raise registry.ScanExecutionUncertain("Child cleanup proof is invalid")
                        await self.update(identifier, state="settled", evidence={
                            "leader_reaped": True, "group_empty": True,
                            "descendants_reaped": True, "cleanup_complete": True,
                        })
                    try:
                        await finish(cleanup())
                    except BaseException as exc:
                        await finish(self.uncertain(identifier, exc))
                        raise
                elif failure is not None:
                    await finish(self.uncertain(identifier, failure))
            finally:
                os.close(read_fd)
                if write_fd >= 0:
                    os.close(write_fd)
        if failure is not None and not timed_out:
            raise failure
        return ProcessResult(proof["exit_code"], *output, timed_out=timed_out)


async def tracked_thread(operation: str, function: Callable[..., T], *args: Any) -> T:
    runtime = current_runtime()
    if runtime is not None:
        return await runtime.thread(operation, function, *args)
    # Standalone library callers still join cancellation; they do not gain a
    # durable scan-execution certificate without the worker-bound registry.
    value, cancelled = await join_task(asyncio.create_task(asyncio.to_thread(function, *args)))
    if cancelled:
        raise asyncio.CancelledError()
    return value
