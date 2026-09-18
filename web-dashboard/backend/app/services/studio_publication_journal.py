"""Acknowledge filesystem intent on the owning event loop before side effects.

Rows survive business/execution deletion and every observed publication remains
an execution blocker. This module neither deletes files nor settles executions.
A missing acknowledgement closes the bridge; no retries or guessed outcomes.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import PurePosixPath
import re
import threading
from typing import Any, NoReturn
from uuid import uuid4

from sqlalchemy import select, text

from app.db.models import StudioPublication
from app.services.host_maintenance_admission import SessionFactory
from app.services.studio_publication_protocol import PublicationObserver
from app.services import studio_resource_registry as registry

_PLAN_KEYS = {"root", "components", "filename", "staging_name", "size_bytes", "checksum"}
_ID_KEYS = {"device", "inode", "kind", "uid", "gid", "mode", "links", "size", "mtime_ns", "ctime_ns"}
_FILE_PHASES = {"staging_intent", "staging_observed", "write_intent", "staged", "link_intent", "published"}


def _fail() -> NoReturn:
    raise registry.StudioResourceUncertain("Studio publication evidence is malformed")


def _component(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value) and value not in {".", ".."}
        and "/" not in value and "\\" not in value
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
        and len(value.encode("utf-8")) <= 220
    )


def validate_plan(plan: Any) -> None:
    if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS:
        _fail()
    root, parts = plan["root"], plan["components"]
    if (
        not isinstance(root, str) or not root.startswith("/") or root in {"/", "//"}
        or len(root) > 4096 or str(PurePosixPath(root)) != root
        or not isinstance(parts, list) or not 4 <= len(parts) <= 64
        or not all(_component(item) for item in parts)
        or parts[:-3] != list(PurePosixPath(root).parts[1:])
        or re.fullmatch(r"revision-[1-9][0-9]{0,9}", parts[-1]) is None
        or not _component(plan["filename"])
        or not isinstance(plan["staging_name"], str)
        or re.fullmatch(r"\.studio-publish-[0-9a-f]{32}\.partial", plan["staging_name"]) is None
        or plan["filename"] == plan["staging_name"]
        or type(plan["size_bytes"]) is not int or plan["size_bytes"] <= 0
        or not isinstance(plan["checksum"], str)
        or re.fullmatch(r"[0-9a-f]{64}", plan["checksum"]) is None
    ):
        _fail()


def _identity(value: Any, kind: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ID_KEYS or value["kind"] != kind:
        _fail()
    if any(type(value[key]) is not int or value[key] < 0 for key in _ID_KEYS - {"kind"}):
        _fail()
    if value["inode"] <= 0 or value["mode"] > 0o7777:
        _fail()
    return value


def _same(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left[key] == right[key] for key in ("device", "inode", "kind", "uid", "gid", "mode"))


def validate_journal(plan: dict[str, Any], events: Any, created_at: Any) -> str:
    """Validate the entire ordered history, including incomplete side effects."""
    validate_plan(plan)
    if not isinstance(events, list) or len(events) > 256 or not registry._aware(created_at):
        _fail()
    phase = "directories"
    next_directory = 0
    directory = None
    pinned = None
    published = False
    previous_stamp = created_at
    for event in events:
        if not isinstance(event, dict) or set(event) != {"operation", "payload", "at"}:
            _fail()
        stamp = registry._stamp(event["at"])
        operation, payload = event["operation"], event["payload"]
        if stamp < previous_stamp or not isinstance(operation, str) or not isinstance(payload, dict):
            _fail()
        previous_stamp = stamp
        if operation == "directory_intent":
            if (
                phase != "directories" or next_directory >= len(plan["components"])
                or set(payload) != {"index", "name", "parent"}
                or type(payload["index"]) is not int or payload["index"] != next_directory
                or payload["name"] != plan["components"][next_directory]
            ):
                _fail()
            parent = _identity(payload["parent"], "directory")
            if directory is not None and not _same(directory, parent):
                _fail()
            phase = operation
        elif operation == "directory_observed":
            if (
                phase != "directory_intent" or set(payload) != {"index", "name", "identity"}
                or type(payload["index"]) is not int or payload["index"] != next_directory
                or payload["name"] != plan["components"][next_directory]
            ):
                _fail()
            directory = _identity(payload["identity"], "directory")
            next_directory += 1
            phase = "directories"
        elif operation == "staging_intent":
            if phase != "directories" or next_directory != len(plan["components"]) or set(payload) != {"directory"}:
                _fail()
            if directory is None or not _same(directory, _identity(payload["directory"], "directory")):
                _fail()
            phase = operation
        else:
            if set(payload) != {"file"}:
                _fail()
            current = _identity(payload["file"], "file")
            if current["mode"] != 0o600 or current["size"] > plan["size_bytes"]:
                _fail()
            if pinned is not None and not _same(pinned, current):
                _fail()
            if operation == "staging_observed":
                valid = phase == "staging_intent" and current["links"] == 1 and current["size"] == 0
            elif operation == "write_intent":
                valid = phase == "staging_observed" and current["links"] == 1 and current["size"] == 0
            elif operation == "staged":
                valid = phase == "write_intent" and current["links"] == 1 and current["size"] == plan["size_bytes"]
            elif operation == "link_intent":
                valid = phase == "staged" and current["links"] == 1 and current["size"] == plan["size_bytes"]
            elif operation == "published":
                valid = phase == "link_intent" and current["links"] == 2 and current["size"] == plan["size_bytes"]
                published = valid
            elif operation == "cleanup_intent":
                valid = phase in _FILE_PHASES and current["links"] in {1, 2}
            elif operation == "staging_removed":
                valid = (
                    phase == "cleanup_intent" and pinned is not None
                    and current["links"] == pinned["links"] - 1 and current["size"] == pinned["size"]
                )
            elif operation == "complete":
                valid = (
                    phase == "staging_removed" and published and current["links"] == 1
                    and current["size"] == plan["size_bytes"]
                )
            else:
                valid = False
            if not valid:
                _fail()
            pinned = current
            phase = operation
    return phase


def validate_row(row: StudioPublication) -> None:
    if (
        not all(registry._uuid(value) for value in (
            row.id, row.execution_id, row.job_id, row.thread_resource_id,
            row.worker_incarnation, row.ownership_nonce,
        ))
        or type(row.admitted_generation) is not int or row.admitted_generation < 7
        or row.state not in {"reserved", "observed"}
        or not registry._aware(row.created_at) or not registry._aware(row.updated_at)
        or row.updated_at < row.created_at
    ):
        _fail()
    phase = validate_journal(row.plan, row.events, row.created_at)
    if (row.state == "observed") != (phase == "complete"):
        _fail()
    if row.events and registry._stamp(row.events[-1]["at"]) != row.updated_at:
        _fail()


async def persist_event(
    *, session_factory: SessionFactory, owner: registry.StudioOwnership,
    thread_resource_id: str, publication_id: str, expected_count: int,
    operation: str, payload: dict[str, Any],
) -> None:
    """One acknowledged event transaction; a stale sequence is never replayed."""
    if (
        not registry._uuid(publication_id) or not registry._uuid(thread_resource_id)
        or type(expected_count) is not int or expected_count < 0
    ):
        _fail()
    async with session_factory() as session:
        await session.execute(text("SET LOCAL lock_timeout = '5s'"))
        execution = await registry._locked(session, owner)
        thread = registry._resources(execution).get(thread_resource_id)
        if (
            thread is None or thread["operation"] != "store_artifact"
            or thread["state"] != "reserved" or execution.phase != "executing"
        ):
            raise registry.StudioOwnershipLost("Publication requires its unjoined storage thread")
        stamp = await registry._now(session)
        row: StudioPublication | None
        if operation == "reserve":
            validate_plan(payload)
            if expected_count != 0 or execution.state != "active":
                raise registry.StudioOwnershipLost("Publication reservation is single-use")
            row = StudioPublication(
                id=publication_id, execution_id=owner.execution_id, job_id=owner.job_id,
                thread_resource_id=thread_resource_id, worker_incarnation=owner.worker_incarnation,
                admitted_generation=owner.admitted_generation, ownership_nonce=owner.nonce,
                state="reserved", plan=deepcopy(payload), events=[], created_at=stamp, updated_at=stamp,
            )
            session.add(row)
        else:
            row = await session.scalar(select(StudioPublication).where(
                StudioPublication.id == publication_id,
            ).with_for_update().execution_options(populate_existing=True))
            if row is None:
                raise registry.StudioOwnershipLost("Publication reservation is missing")
            validate_row(row)
            if (
                row.execution_id != owner.execution_id or row.job_id != owner.job_id
                or row.thread_resource_id != thread_resource_id or row.ownership_nonce != owner.nonce
                or row.worker_incarnation != owner.worker_incarnation
                or row.admitted_generation != owner.admitted_generation
                or row.state != "reserved" or len(row.events) != expected_count
            ):
                raise registry.StudioOwnershipLost("Publication ownership or sequence differs")
            events = [*row.events, {"operation": operation, "payload": deepcopy(payload), "at": stamp.isoformat()}]
            phase = validate_journal(row.plan, events, row.created_at)
            row.events, row.updated_at = events, stamp
            row.state = "observed" if phase == "complete" else "reserved"
        validate_row(row)
        await session.commit()


def make_publication_observer(
    session_factory: SessionFactory, owner: registry.StudioOwnership, thread_resource_id: str,
) -> PublicationObserver:
    """Only the owned blocking thread may wait for the owning loop's database.

    No cross-loop session, timeout, resubmission or cancellation-as-acknowledgment.
    The thread's joined wrapper outlives caller cancellation and waits for this
    bridge. On error, all later mutations (including cleanup) must fail closed.
    """
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    publisher_thread: int | None = None
    identifier = str(uuid4())
    count = 0
    reserved = False
    failed = False
    guard = threading.Lock()

    def observe(operation: str, payload: dict[str, Any]) -> None:
        nonlocal count, reserved, failed, publisher_thread
        if threading.get_ident() == loop_thread:
            raise registry.StudioResourceUncertain("Publication observer cannot block its event loop")
        with guard:
            if failed or (publisher_thread is not None and publisher_thread != threading.get_ident()):
                raise registry.StudioResourceUncertain("Publication bridge no longer authorizes mutation")
            publisher_thread = threading.get_ident()
            if (operation == "reserve") == reserved:
                failed = True
                raise registry.StudioResourceUncertain("Publication reservation order differs")
            coroutine = persist_event(
                session_factory=session_factory, owner=owner, thread_resource_id=thread_resource_id,
                publication_id=identifier, expected_count=count, operation=operation, payload=deepcopy(payload),
            )
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            except BaseException:
                coroutine.close()
                failed = True
                raise
            try:
                future.result()
            except BaseException as error:
                failed = True
                raise registry.StudioResourceUncertain(
                    "Studio publication acknowledgement is unavailable"
                ) from error
            if operation == "reserve":
                reserved = True
            else:
                count += 1
    return observe
