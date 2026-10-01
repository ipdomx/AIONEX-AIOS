#!/usr/bin/env python3
"""Reconcile stale local Identity Media failures after read-only provider proof.

Scope is intentionally narrow: Replicate executions already terminal as local
status=failed but whose stored provider_state is still starting/processing.
The operator performs no provider mutation, retry, submission, cancellation,
download, or new claim. It queries Replicate once per candidate and accepts only
provider terminal states failed/canceled. A create-only fsynced intent binds the
execution id, row version and SHA-256 of the provider job id before the one DB
settlement transaction. Uncertain intents are never replayed blindly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path("/opt/AIOS")
BASE = Path("/var/lib/aionex/fr06-final-maintenance")
SCHEMA = "aionex.fr06c5d15-identity-terminal-reconcile.v1"
MAX_CANDIDATES = 16

AUTHORITY_READER = r'''import asyncio,json
from app.db.base import SessionLocal
from app.services.host_maintenance_admission import read_admission_snapshot
async def main():
 async with SessionLocal() as s:
  x=await read_admission_snapshot(s,required_scope="realtime_media_requests")
  print(json.dumps({"schema_version":x.schema_version,"generation":x.generation,
   "status":x.status,"enabled":x.enabled,"operation_id":x.operation_id,
   "full_host_closure":x.full_host_closure}))
asyncio.run(main())'''

CANDIDATE_READER = r'''import asyncio,hashlib,json
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db.models import IdentityMediaExecution
async def main():
 async with SessionLocal() as s:
  rows=(await s.scalars(select(IdentityMediaExecution).where(
   IdentityMediaExecution.provider=="replicate",
   IdentityMediaExecution.status=="failed",
   IdentityMediaExecution.provider_state.in_(("starting","processing")),
   IdentityMediaExecution.provider_job_id.is_not(None)
  ).order_by(IdentityMediaExecution.created_at,IdentityMediaExecution.id))).all()
  out=[]
  for x in rows:
   out.append({"execution_id":x.id,"version":x.version,"provider_state":x.provider_state,
    "job_sha256":hashlib.sha256(x.provider_job_id.encode()).hexdigest(),
    "lease_present":x.lease_token is not None,
    "secondary_job_present":x.secondary_provider_job_id is not None,
    "completed":x.completed_at is not None})
  print(json.dumps(out))
asyncio.run(main())'''

PROVIDER_READER = r'''import asyncio,hashlib,json,sys
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db.models import IdentityMediaExecution
from app.core.config import settings
from app.services.identity_media_replicate import ReplicateIdentityMediaAdapter
async def main():
 eid=sys.argv[1]
 async with SessionLocal() as s:
  x=await s.scalar(select(IdentityMediaExecution).where(IdentityMediaExecution.id==eid))
  if x is None: raise RuntimeError("execution missing")
  if x.provider!="replicate" or x.status!="failed" or x.provider_state not in {"starting","processing"}:
   raise RuntimeError("execution baseline changed")
  if not x.provider_job_id or x.lease_token is not None or x.secondary_provider_job_id is not None or x.completed_at is None:
   raise RuntimeError("execution ownership is not reconcilable")
  job_hash=hashlib.sha256(x.provider_job_id.encode()).hexdigest()
  adapter=ReplicateIdentityMediaAdapter(str(settings.REPLICATE_API_TOKEN or "").strip(),timeout_seconds=30)
  result=await adapter.get_prediction(x.provider_job_id)
  print(json.dumps({"execution_id":x.id,"version":x.version,"provider_state":x.provider_state,
   "job_sha256":job_hash,"provider_terminal_state":result.status}))
asyncio.run(main())'''

SETTLE = r'''import asyncio,hashlib,json,sys
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db.models import IdentityMediaExecution,AuditEvent
from app.services.host_maintenance_admission import read_admission_snapshot
async def main():
 eid,version,job_hash,target=sys.argv[1],int(sys.argv[2]),sys.argv[3],sys.argv[4]
 op,gen=sys.argv[5],int(sys.argv[6])
 if target not in {"failed","canceled"}: raise RuntimeError("terminal target rejected")
 async with SessionLocal() as s:
  async with s.begin():
   authority=await read_admission_snapshot(s,required_scope="realtime_media_requests")
   if (authority.schema_version!=8 or authority.operation_id!=op or authority.generation!=gen
       or authority.status!="closed" or authority.enabled is not False
       or authority.full_host_closure is not False):
    raise RuntimeError("maintenance authority changed before settlement")
   x=await s.scalar(select(IdentityMediaExecution).where(
    IdentityMediaExecution.id==eid
   ).with_for_update())
   if x is None: raise RuntimeError("execution missing")
   actual=hashlib.sha256((x.provider_job_id or "").encode()).hexdigest()
   if (x.provider!="replicate" or x.status!="failed" or x.provider_state not in {"starting","processing"}
       or x.version!=version or actual!=job_hash or x.lease_token is not None
       or x.secondary_provider_job_id is not None or x.completed_at is None):
    raise RuntimeError("execution settlement baseline changed")
   before=x.provider_state
   x.provider_state=target
   x.version+=1
   s.add(AuditEvent(organization_id=x.organization_id,user_id=x.requested_by_id,
    action="identity_media.execution.provider_terminal_reconciled",
    resource_type="identity_media_execution",resource_id=x.id,
    details={"provider":"replicate","before_provider_state":before,
     "maintenance_operation_id":op,"maintenance_generation":gen,
     "provider_terminal_state":target,"external_effect":"read_only_provider_observation"}))
  print(json.dumps({"execution_id":x.id,"version":x.version,"status":x.status,
   "provider_state":x.provider_state,"job_sha256":job_hash}))
asyncio.run(main())'''

STATE_READER = r'''import asyncio,hashlib,json,sys
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db.models import IdentityMediaExecution
async def main():
 eid=sys.argv[1]
 async with SessionLocal() as s:
  x=await s.scalar(select(IdentityMediaExecution).where(IdentityMediaExecution.id==eid))
  if x is None: raise RuntimeError("execution missing")
  print(json.dumps({"execution_id":x.id,"version":x.version,"status":x.status,
   "provider_state":x.provider_state,
   "job_sha256":hashlib.sha256((x.provider_job_id or "").encode()).hexdigest(),
   "lease_present":x.lease_token is not None,
   "secondary_job_present":x.secondary_provider_job_id is not None,
   "completed":x.completed_at is not None}))
asyncio.run(main())'''


class IdentityTerminalReconcileHalted(RuntimeError):
    """Reconciliation cannot proceed without risking a wrong/duplicate settlement."""


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _run(args: list[str], timeout: int = 45) -> str:
    result = subprocess.run(
        args, text=True, capture_output=True, check=False, timeout=timeout
    )
    if result.returncode:
        raise IdentityTerminalReconcileHalted(
            "fixed reconciliation command failed; no retry performed"
        )
    return result.stdout.strip()


def _inside(program: str, *args: str) -> Any:
    raw = _run(
        [
            "docker",
            "exec",
            "web-dashboard-backend-1",
            "/opt/venv/bin/python",
            "-c",
            program,
            *args,
        ]
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IdentityTerminalReconcileHalted("backend reconciliation JSON invalid") from exc


def _source() -> dict[str, str]:
    head = _run(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    origin = _run(["git", "-C", str(ROOT), "rev-parse", "origin/main"])
    dirty = _run(["git", "-C", str(ROOT), "status", "--porcelain"])
    if head != origin or dirty:
        raise IdentityTerminalReconcileHalted(
            "production source is not clean exact origin/main"
        )
    return {"source_commit": head}


def _authority(operation_id: str, generation: int) -> dict[str, Any]:
    value = _inside(AUTHORITY_READER)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "generation",
            "status",
            "enabled",
            "operation_id",
            "full_host_closure",
        }
        or value["schema_version"] != 8
        or value["generation"] != generation
        or value["operation_id"] != operation_id
        or value["status"] != "closed"
        or value["enabled"] is not False
        or value["full_host_closure"] is not False
    ):
        raise IdentityTerminalReconcileHalted("exact closed schema-8 authority required")
    return value


def _root(path: Path) -> int:
    resolved = path.resolve(strict=False)
    base = BASE.resolve()
    if resolved == base or base not in resolved.parents:
        raise IdentityTerminalReconcileHalted("operation-private journal root required")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.geteuid()
    ):
        raise IdentityTerminalReconcileHalted("root-owned 0700 journal required")
    return os.open(
        path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )


def _canon(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def _write(fd: int, name: str, value: Any) -> None:
    data = _canon(value)
    out = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=fd,
    )
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(out, data[offset:])
        os.fsync(out)
    finally:
        os.close(out)
    os.fsync(fd)


def _read(fd: int, name: str) -> dict[str, Any]:
    src = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
    )
    try:
        info = os.fstat(src)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 65536
        ):
            raise IdentityTerminalReconcileHalted("unsafe reconciliation record")
        raw = os.read(src, info.st_size + 1)
        if len(raw) != info.st_size or not raw.endswith(b"\n"):
            raise IdentityTerminalReconcileHalted("incomplete reconciliation record")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise IdentityTerminalReconcileHalted("reconciliation object required")
        return value
    finally:
        os.close(src)


def _exists(fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _candidate_binding(item: Any) -> dict[str, Any]:
    if (
        not isinstance(item, dict)
        or set(item)
        != {
            "execution_id",
            "version",
            "provider_state",
            "job_sha256",
        }
        or not isinstance(item["execution_id"], str)
        or not item["execution_id"]
        or len(item["execution_id"]) > 36
        or type(item["version"]) is not int
        or item["version"] < 0
        or item["provider_state"] not in {"starting", "processing"}
        or not isinstance(item["job_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", item["job_sha256"]) is None
    ):
        raise IdentityTerminalReconcileHalted("frozen candidate binding is invalid")
    return dict(item)


def _validate_session(
    value: Any,
    *,
    operation_id: str,
    generation: int,
    authority: dict[str, Any],
    source: dict[str, str],
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema",
            "operation_id",
            "generation",
            "authority",
            "source",
            "candidate_count",
            "candidates",
            "provider_effect",
            "automatic_retry",
            "full_host_closure",
        }
        or value["schema"] != SCHEMA
        or value["operation_id"] != operation_id
        or value["generation"] != generation
        or value["authority"] != authority
        or value["source"] != source
        or value["provider_effect"] != "read_only_get_prediction"
        or value["automatic_retry"] is not False
        or value["full_host_closure"] is not False
        or not isinstance(value["candidates"], list)
        or type(value["candidate_count"]) is not int
        or value["candidate_count"] != len(value["candidates"])
        or value["candidate_count"] > MAX_CANDIDATES
    ):
        raise IdentityTerminalReconcileHalted("frozen reconciliation session is invalid")
    frozen = [_candidate_binding(item) for item in value["candidates"]]
    if len({item["execution_id"] for item in frozen}) != len(frozen):
        raise IdentityTerminalReconcileHalted("duplicate execution in frozen session")
    return {**value, "candidates": frozen}


def _candidates() -> list[dict[str, Any]]:
    value = _inside(CANDIDATE_READER)
    if not isinstance(value, list) or len(value) > MAX_CANDIDATES:
        raise IdentityTerminalReconcileHalted("candidate set invalid or exceeds bound")
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "execution_id",
                "version",
                "provider_state",
                "job_sha256",
                "lease_present",
                "secondary_job_present",
                "completed",
            }
            or not isinstance(item["execution_id"], str)
            or type(item["version"]) is not int
            or item["version"] < 0
            or item["provider_state"] not in {"starting", "processing"}
            or not isinstance(item["job_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", item["job_sha256"]) is None
            or item["lease_present"] is not False
            or item["secondary_job_present"] is not False
            or item["completed"] is not True
        ):
            raise IdentityTerminalReconcileHalted("candidate baseline is not safely reconcilable")
    return value


def _provider_observation(execution_id: str) -> dict[str, Any]:
    value = _inside(PROVIDER_READER, execution_id)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "execution_id",
            "version",
            "provider_state",
            "job_sha256",
            "provider_terminal_state",
        }
        or value["execution_id"] != execution_id
        or value["provider_state"] not in {"starting", "processing"}
        or value["provider_terminal_state"] not in {"failed", "canceled"}
        or not isinstance(value["job_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["job_sha256"]) is None
    ):
        raise IdentityTerminalReconcileHalted(
            "provider did not prove an accepted terminal failure"
        )
    return value


def _state(execution_id: str) -> dict[str, Any]:
    value = _inside(STATE_READER, execution_id)
    if not isinstance(value, dict):
        raise IdentityTerminalReconcileHalted("execution state invalid")
    return value


def _settle(observation: dict[str, Any]) -> dict[str, Any]:
    value = _inside(
        SETTLE,
        observation["execution_id"],
        str(observation["version"]),
        observation["job_sha256"],
        observation["provider_terminal_state"],
        observation["operation_id"],
        str(observation["generation"]),
    )
    if (
        not isinstance(value, dict)
        or value.get("execution_id") != observation["execution_id"]
        or value.get("version") != observation["version"] + 1
        or value.get("status") != "failed"
        or value.get("provider_state") != observation["provider_terminal_state"]
        or value.get("job_sha256") != observation["job_sha256"]
    ):
        raise IdentityTerminalReconcileHalted("settlement result differs")
    return value


def execute(
    *,
    operation_id: str,
    generation: int,
    journal_root: Path,
) -> dict[str, Any]:
    if not _uuid(operation_id) or type(generation) is not int or generation < 8:
        raise IdentityTerminalReconcileHalted("valid operation/generation required")
    authority = _authority(operation_id, generation)
    source = _source()
    fd = _root(journal_root)
    try:
        final_name = "identity-terminal-reconcile-accepted.json"
        if _exists(fd, final_name):
            existing = _read(fd, final_name)
            if (
                existing.get("schema") != SCHEMA
                or existing.get("operation_id") != operation_id
                or existing.get("generation") != generation
                or existing.get("source") != source
                or existing.get("authority") != authority
                or existing.get("remaining_reconcilable_count") != 0
                or _candidates()
            ):
                raise IdentityTerminalReconcileHalted(
                    "accepted reconciliation no longer matches current state"
                )
            return existing
        session_name = "reconcile-session-intent.json"
        if _exists(fd, session_name):
            session = _validate_session(
                _read(fd, session_name),
                operation_id=operation_id,
                generation=generation,
                authority=authority,
                source=source,
            )
        else:
            candidates = _candidates()
            session = {
                "schema": SCHEMA,
                "operation_id": operation_id,
                "generation": generation,
                "authority": authority,
                "source": source,
                "candidate_count": len(candidates),
                "candidates": [
                    {
                        "execution_id": x["execution_id"],
                        "version": x["version"],
                        "provider_state": x["provider_state"],
                        "job_sha256": x["job_sha256"],
                    }
                    for x in candidates
                ],
                "provider_effect": "read_only_get_prediction",
                "automatic_retry": False,
                "full_host_closure": False,
            }
            session = _validate_session(
                session,
                operation_id=operation_id,
                generation=generation,
                authority=authority,
                source=source,
            )
            _write(fd, session_name, session)

        accepted: list[dict[str, Any]] = []
        for index, candidate in enumerate(session["candidates"]):
            intent_name = f"{index:02d}-settle-intent.json"
            accepted_name = f"{index:02d}-settle-accepted.json"
            if _exists(fd, accepted_name):
                receipt = _read(fd, accepted_name)
                current = _state(candidate["execution_id"])
                if (
                    current.get("execution_id") != candidate["execution_id"]
                    or current.get("version") != candidate["version"] + 1
                    or current.get("status") != "failed"
                    or current.get("provider_state") != receipt.get("provider_terminal_state")
                    or current.get("job_sha256") != candidate["job_sha256"]
                    or current.get("lease_present") is not False
                    or current.get("secondary_job_present") is not False
                    or current.get("completed") is not True
                ):
                    raise IdentityTerminalReconcileHalted("accepted settlement no longer matches")
                accepted.append(receipt)
                continue

            if _exists(fd, intent_name):
                intent = _read(fd, intent_name)
                current = _state(candidate["execution_id"])
                target = intent.get("provider_terminal_state")
                if (
                    current.get("execution_id") == candidate["execution_id"]
                    and current.get("version") == candidate["version"] + 1
                    and current.get("status") == "failed"
                    and current.get("provider_state") == target
                    and current.get("job_sha256") == candidate["job_sha256"]
                    and current.get("lease_present") is False
                    and current.get("secondary_job_present") is False
                    and current.get("completed") is True
                ):
                    receipt = {
                        "execution_id": candidate["execution_id"],
                        "job_sha256": candidate["job_sha256"],
                        "before_version": candidate["version"],
                        "after_version": candidate["version"] + 1,
                        "provider_terminal_state": target,
                        "reconciled_after_intent": True,
                        "replayed_settlement": False,
                    }
                    _write(fd, accepted_name, receipt)
                    accepted.append(receipt)
                    continue
                raise IdentityTerminalReconcileHalted(
                    "unresolved settlement intent; refusing replay"
                )

            _authority(operation_id, generation)
            if _source() != source:
                raise IdentityTerminalReconcileHalted("source changed before provider observation")
            observation = _provider_observation(candidate["execution_id"])
            if (
                observation["version"] != candidate["version"]
                or observation["provider_state"] != candidate["provider_state"]
                or observation["job_sha256"] != candidate["job_sha256"]
            ):
                raise IdentityTerminalReconcileHalted(
                    "local row changed during provider observation"
                )
            intent = {
                "schema": SCHEMA,
                "operation_id": operation_id,
                "generation": generation,
                "execution_id": candidate["execution_id"],
                "before_version": candidate["version"],
                "before_provider_state": candidate["provider_state"],
                "job_sha256": candidate["job_sha256"],
                "provider_terminal_state": observation["provider_terminal_state"],
                "effect": "settle_provider_state_only",
                "automatic_retry": False,
            }
            _write(fd, intent_name, intent)
            _authority(operation_id, generation)
            if _source() != source:
                raise IdentityTerminalReconcileHalted("source changed before settlement; intent retained")
            settled = _settle({**observation, "operation_id": operation_id, "generation": generation})
            receipt = {
                "execution_id": candidate["execution_id"],
                "job_sha256": candidate["job_sha256"],
                "before_version": candidate["version"],
                "after_version": settled["version"],
                "provider_terminal_state": settled["provider_state"],
                "reconciled_after_intent": False,
                "replayed_settlement": False,
            }
            _write(fd, accepted_name, receipt)
            accepted.append(receipt)

        remaining = _candidates()
        if remaining:
            raise IdentityTerminalReconcileHalted(
                "reconcilable nonterminal provider states remain after settlement"
            )
        _authority(operation_id, generation)
        result = {
            "schema": SCHEMA,
            "operation_id": operation_id,
            "generation": generation,
            "source": source,
            "authority": authority,
            "reconciled_count": len(accepted),
            "provider_terminal_states": sorted(
                x["provider_terminal_state"] for x in accepted
            ),
            "remaining_reconcilable_count": 0,
            "provider_mutation_performed": False,
            "provider_query_only": True,
            "business_status_changed": False,
            "full_host_closure": False,
            "production_activation_authorized": False,
        }
        _write(fd, final_name, result)
        return result
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--journal-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = execute(
            operation_id=args.operation_id,
            generation=args.generation,
            journal_root=args.journal_root,
        )
    except (
        IdentityTerminalReconcileHalted,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ):
        print(json.dumps({"status": "FR06_IDENTITY_TERMINAL_RECONCILE_HALTED"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
