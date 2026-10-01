#!/usr/bin/env python3
"""Journal one fresh platform backup plus independent local/R2 restore validation.

This operator runs only while the exact schema-8 maintenance authority is OPEN
for one existing operation/generation. It uses the existing Owner backup APIs
and worker. It never performs an in-place restore and never changes admission.

Every enqueue has a create-only fsynced intent. If command output is lost, a
later invocation may reconcile exactly one durable record matching the unique
operation/generation label; it never blindly enqueues again. Any ambiguous or
failed record halts and preserves the journal for explicit reconciliation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path("/opt/AIOS")
BASE = Path("/var/lib/aionex/fr06-final-maintenance")
SCHEMA = "aionex.fr06c5d14-maintenance-recovery-refresh.v1"
MAX_WAIT_SECONDS = 600

AUTHORITY_READER = r'''import asyncio,json
from app.db.base import SessionLocal
from app.services.host_maintenance_admission import read_admission_snapshot
async def main():
 async with SessionLocal() as s:
  x=await read_admission_snapshot(s,required_scope="realtime_media_requests")
  print(json.dumps({"schema_version":x.schema_version,"scope":x.scope,
   "generation":x.generation,"status":x.status,"enabled":x.enabled,
   "operation_id":x.operation_id,"full_host_closure":x.full_host_closure}))
asyncio.run(main())'''

OWNER_PREFIX = r'''from sqlalchemy import select
from app.db.base import SessionLocal
from app.db.models import User,Role,BackupRecord,DisasterRecoveryRun
from app.core.auth import auth_service,require_super_owner
async def owner(s):
 ids=list((await s.scalars(select(User.id).join(Role,User.role_id==Role.id).where(
  Role.name=="Super Owner",User.deleted_at.is_(None),User.status.in_(("active","online"))
 ))).all())
 if len(ids)!=1: raise RuntimeError("single active Super Owner required")
 actor=await auth_service.get_user_by_id(s,ids[0])
 await require_super_owner(actor)
 return actor
'''

class RecoveryRefreshHalted(RuntimeError):
    """The refresh cannot continue without risking duplicate durable work."""


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _run(args: list[str], *, timeout: int = 30) -> str:
    result = subprocess.run(
        args, text=True, capture_output=True, check=False, timeout=timeout
    )
    if result.returncode:
        raise RecoveryRefreshHalted("fixed recovery command failed; no automatic retry")
    return result.stdout.strip()


def _canon(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def _journal_root(path: Path) -> int:
    resolved = path.resolve(strict=False)
    base = BASE.resolve()
    if resolved == base or base not in resolved.parents:
        raise RecoveryRefreshHalted("journal must be an operation-private child")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.geteuid()
    ):
        raise RecoveryRefreshHalted("root-owned 0700 journal required")
    return os.open(
        path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )


def _write_new(fd: int, name: str, value: Any) -> None:
    data = _canon(value)
    out = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=fd,
    )
    try:
        written = 0
        while written < len(data):
            written += os.write(out, data[written:])
        os.fsync(out)
    finally:
        os.close(out)
    os.fsync(fd)


def _read(fd: int, name: str) -> Any:
    source = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
    )
    try:
        info = os.fstat(source)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 1024 * 1024
        ):
            raise RecoveryRefreshHalted("unsafe recovery journal record")
        raw = os.read(source, info.st_size + 1)
        if len(raw) != info.st_size or not raw.endswith(b"\n"):
            raise RecoveryRefreshHalted("incomplete recovery journal record")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RecoveryRefreshHalted("journal object required")
        return value
    finally:
        os.close(source)


def _exists(fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _source() -> dict[str, str]:
    head = _run(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    origin = _run(["git", "-C", str(ROOT), "rev-parse", "origin/main"])
    dirty = _run(["git", "-C", str(ROOT), "status", "--porcelain"])
    if head != origin or dirty:
        raise RecoveryRefreshHalted("production source is not clean exact origin/main")
    return {"source_commit": head}


def _inside(program: str) -> dict[str, Any]:
    raw = _run(
        [
            "docker",
            "exec",
            "web-dashboard-backend-1",
            "/opt/venv/bin/python",
            "-c",
            program,
        ],
        timeout=45,
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryRefreshHalted("backend recovery result is not JSON") from exc
    if not isinstance(value, dict):
        raise RecoveryRefreshHalted("backend recovery object required")
    return value


def _authority(operation_id: str, generation: int) -> dict[str, Any]:
    value = _inside(AUTHORITY_READER)
    required = {
        "schema_version",
        "scope",
        "generation",
        "status",
        "enabled",
        "operation_id",
        "full_host_closure",
    }
    if (
        set(value) != required
        or value["schema_version"] != 8
        or value["operation_id"] != operation_id
        or value["generation"] != generation
        or value["status"] != "open"
        or value["enabled"] is not True
        or value["full_host_closure"] is not False
    ):
        raise RecoveryRefreshHalted("exact open schema-8 authority required")
    return value


def _enqueue_backup(kind: str) -> dict[str, Any]:
    program = (
        "import asyncio,json\n"
        + OWNER_PREFIX
        + r'''
from app.api.v1.endpoints.backups import create_backup
async def main():
 async with SessionLocal() as s:
  actor=await owner(s)
  row=await create_backup(name=KIND,scope="platform",actor=actor,session=s)
  print(json.dumps({"backup_id":row["id"],"status":row["status"]}))
asyncio.run(main())'''
    ).replace("KIND", repr(kind))
    return _inside(program)


def _find_backups(kind: str) -> list[dict[str, Any]]:
    program = r'''import asyncio,json
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db.models import BackupRecord
async def main():
 async with SessionLocal() as s:
  rows=(await s.scalars(select(BackupRecord).where(
   BackupRecord.kind==KIND,BackupRecord.scope=="platform"
  ).order_by(BackupRecord.created_at.asc()))).all()
  print(json.dumps([{"id":x.id,"status":x.status} for x in rows]))
asyncio.run(main())'''.replace("KIND", repr(kind))
    raw = _run(
        [
            "docker",
            "exec",
            "web-dashboard-backend-1",
            "/opt/venv/bin/python",
            "-c",
            program,
        ],
        timeout=30,
    )
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryRefreshHalted("backup reconciliation JSON invalid") from exc
    if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
        raise RecoveryRefreshHalted("backup reconciliation list invalid")
    return rows


def _backup_state(backup_id: str) -> dict[str, Any]:
    program = r'''import asyncio,json
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db.models import BackupRecord
async def main():
 async with SessionLocal() as s:
  x=await s.get(BackupRecord,BID)
  if x is None: raise RuntimeError("backup missing")
  print(json.dumps({"id":x.id,"kind":x.kind,"scope":x.scope,"status":x.status,
   "offsite_status":x.offsite_status,"offsite_encrypted":bool(
    isinstance(x.offsite_evidence,dict) and x.offsite_evidence.get("encryption_required") is True),
   "checksum_present":bool(x.checksum),"size_bytes":x.size_bytes,
   "created_at":x.created_at.isoformat() if x.created_at else None,
   "completed_at":x.completed_at.isoformat() if x.completed_at else None}))
asyncio.run(main())'''.replace("BID", repr(backup_id))
    return _inside(program)


def _enqueue_restore(backup_id: str) -> dict[str, Any]:
    program = (
        "import asyncio,json\n"
        + OWNER_PREFIX
        + r'''
from app.api.v1.endpoints.backups import _enqueue_restore_validation
async def main():
 async with SessionLocal() as s:
  b=await s.get(BackupRecord,BID)
  if b is None or b.status!="completed" or b.offsite_status!="completed":
   raise RuntimeError("completed backup required")
  if not isinstance(b.offsite_evidence,dict) or b.offsite_evidence.get("encryption_required") is not True:
   raise RuntimeError("encrypted offsite evidence required")
  actor=await owner(s)
  _,run=await _enqueue_restore_validation(
   backup_id=b.id,operation="restore_validation",actor=actor,session=s
  )
  await s.commit()
  print(json.dumps({"backup_id":b.id,"restore_id":run.id,"status":run.status}))
asyncio.run(main())'''
    ).replace("BID", repr(backup_id))
    return _inside(program)


def _find_restores(backup_id: str) -> list[dict[str, Any]]:
    program = r'''import asyncio,json
from sqlalchemy import select
from app.db.base import SessionLocal
from app.db.models import DisasterRecoveryRun
async def main():
 async with SessionLocal() as s:
  rows=(await s.scalars(select(DisasterRecoveryRun).where(
   DisasterRecoveryRun.operation=="restore_validation"
  ).order_by(DisasterRecoveryRun.created_at.asc()))).all()
  out=[]
  for x in rows:
   d=x.details if isinstance(x.details,dict) else {}
   if d.get("backup_id")==BID:
    out.append({"id":x.id,"status":x.status})
  print(json.dumps(out))
asyncio.run(main())'''.replace("BID", repr(backup_id))
    raw = _run(
        [
            "docker",
            "exec",
            "web-dashboard-backend-1",
            "/opt/venv/bin/python",
            "-c",
            program,
        ],
        timeout=30,
    )
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryRefreshHalted("restore reconciliation JSON invalid") from exc
    if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
        raise RecoveryRefreshHalted("restore reconciliation list invalid")
    return rows


def _restore_state(restore_id: str) -> dict[str, Any]:
    program = r'''import asyncio,json
from sqlalchemy import text
from app.db.base import SessionLocal
async def main():
 async with SessionLocal() as s:
  await s.execute(text("SET TRANSACTION READ ONLY"))
  row=(await s.execute(text(
   "SELECT id,status,created_at,completed_at,details FROM disaster_recovery_runs WHERE id=:id"
  ),{"id":RID})).mappings().one()
  d=row["details"] if isinstance(row["details"],dict) else {}
  scratch=await s.scalar(text("SELECT count(*) FROM pg_database WHERE datname LIKE 'aionex_restore_%'"))
  print(json.dumps({"id":row["id"],"status":row["status"],
   "created_at":row["created_at"].isoformat() if row["created_at"] else None,
   "completed_at":row["completed_at"].isoformat() if row["completed_at"] else None,
   "backup_id":d.get("backup_id"),"validated":d.get("validated"),
   "offsite_validated":d.get("offsite_validated"),
   "three_d_snapshot_validated":d.get("three_d_snapshot_validated"),
   "offsite_three_d_snapshot_validated":d.get("offsite_three_d_snapshot_validated"),
   "checksum_present":bool(d.get("checksum")),
   "checksums_match":bool(d.get("checksum")) and d.get("checksum")==d.get("offsite_database_checksum"),
   "size_bytes":d.get("size_bytes"),"scratch_databases":scratch}))
  await s.rollback()
asyncio.run(main())'''.replace("RID", repr(restore_id))
    return _inside(program)


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise RecoveryRefreshHalted(f"{field} missing")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RecoveryRefreshHalted(f"{field} malformed") from exc
    if result.utcoffset() is None:
        raise RecoveryRefreshHalted(f"{field} lacks timezone")
    return result


def _poll(
    getter,
    identity: str,
    *,
    operation_id: str,
    generation: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    while True:
        _authority(operation_id, generation)
        value = getter(identity)
        status = value.get("status")
        if status == "completed":
            return value
        if status not in {"pending", "running"}:
            raise RecoveryRefreshHalted("durable recovery job failed; no automatic replay")
        if time.monotonic() >= deadline:
            raise RecoveryRefreshHalted(
                "durable recovery job still pending; reconcile saved ID on a later run"
            )
        time.sleep(2)


def execute(
    *,
    operation_id: str,
    generation: int,
    journal_root: Path,
) -> dict[str, Any]:
    if not _uuid(operation_id) or type(generation) is not int or generation < 8:
        raise RecoveryRefreshHalted("valid operation/generation required")
    authority = _authority(operation_id, generation)
    source = _source()
    fd = _journal_root(journal_root)
    try:
        label = f"fr06-c5d14-{operation_id[:8]}-g{generation}"
        session_name = "recovery-session-intent.json"
        if not _exists(fd, session_name):
            _write_new(
                fd,
                session_name,
                {
                    "schema": SCHEMA,
                    "operation_id": operation_id,
                    "generation": generation,
                    "authority": authority,
                    "source": source,
                    "backup_kind": label,
                    "scope": "platform",
                    "in_place_restore": False,
                    "automatic_retry": False,
                },
            )
        session = _read(fd, session_name)
        if (
            session.get("schema") != SCHEMA
            or session.get("operation_id") != operation_id
            or session.get("generation") != generation
            or session.get("authority") != authority
            or session.get("source") != source
            or session.get("backup_kind") != label
            or session.get("scope") != "platform"
            or session.get("in_place_restore") is not False
            or session.get("automatic_retry") is not False
        ):
            raise RecoveryRefreshHalted("existing recovery session differs")

        backup_intent = "backup-enqueue-intent.json"
        backup_request = "backup-enqueue-accepted.json"
        if _exists(fd, backup_request):
            backup_receipt = _read(fd, backup_request)
            backup_id = backup_receipt.get("backup_id")
        elif _exists(fd, backup_intent):
            matches = _find_backups(label)
            if len(matches) != 1:
                raise RecoveryRefreshHalted(
                    "backup enqueue intent unresolved; refusing duplicate enqueue"
                )
            backup_id = matches[0].get("id")
            if not isinstance(backup_id, str):
                raise RecoveryRefreshHalted("reconciled backup id invalid")
            backup_receipt = {
                "backup_id": backup_id,
                "reconciled_after_intent": True,
                "replayed_enqueue": False,
            }
            _write_new(fd, backup_request, backup_receipt)
        else:
            preexisting = _find_backups(label)
            if preexisting:
                raise RecoveryRefreshHalted(
                    "preexisting backup label without journal; refusing duplicate enqueue"
                )
            _authority(operation_id, generation)
            _write_new(
                fd,
                backup_intent,
                {
                    "operation_id": operation_id,
                    "generation": generation,
                    "backup_kind": label,
                    "scope": "platform",
                    "automatic_retry": False,
                },
            )
            _authority(operation_id, generation)
            created = _enqueue_backup(label)
            backup_id = created.get("backup_id")
            if not isinstance(backup_id, str) or created.get("status") != "pending":
                raise RecoveryRefreshHalted(
                    "backup enqueue result uncertain; intent retained"
                )
            backup_receipt = {
                "backup_id": backup_id,
                "reconciled_after_intent": False,
                "replayed_enqueue": False,
            }
            _write_new(fd, backup_request, backup_receipt)

        if not isinstance(backup_id, str):
            raise RecoveryRefreshHalted("backup id unavailable")
        backup = _poll(
            _backup_state,
            backup_id,
            operation_id=operation_id,
            generation=generation,
        )
        if (
            backup.get("kind") != label
            or backup.get("scope") != "platform"
            or backup.get("offsite_status") != "completed"
            or backup.get("offsite_encrypted") is not True
            or backup.get("checksum_present") is not True
            or type(backup.get("size_bytes")) is not int
            or backup["size_bytes"] <= 0
        ):
            raise RecoveryRefreshHalted("completed backup lacks accepted encrypted offsite evidence")
        _parse_time(backup.get("completed_at"), "backup completed_at")
        if _exists(fd, "backup-completed.json"):
            if _read(fd, "backup-completed.json") != backup:
                raise RecoveryRefreshHalted("backup completion receipt differs")
        else:
            _write_new(fd, "backup-completed.json", backup)

        restore_intent = "restore-enqueue-intent.json"
        restore_request = "restore-enqueue-accepted.json"
        if _exists(fd, restore_request):
            restore_receipt = _read(fd, restore_request)
            restore_id = restore_receipt.get("restore_id")
        elif _exists(fd, restore_intent):
            matches = _find_restores(backup_id)
            if len(matches) != 1:
                raise RecoveryRefreshHalted(
                    "restore enqueue intent unresolved; refusing duplicate enqueue"
                )
            restore_id = matches[0].get("id")
            if not isinstance(restore_id, str):
                raise RecoveryRefreshHalted("reconciled restore id invalid")
            restore_receipt = {
                "backup_id": backup_id,
                "restore_id": restore_id,
                "reconciled_after_intent": True,
                "replayed_enqueue": False,
                "in_place_restore": False,
            }
            _write_new(fd, restore_request, restore_receipt)
        else:
            _authority(operation_id, generation)
            _write_new(
                fd,
                restore_intent,
                {
                    "operation_id": operation_id,
                    "generation": generation,
                    "backup_id": backup_id,
                    "operation": "restore_validation",
                    "in_place_restore": False,
                    "automatic_retry": False,
                },
            )
            _authority(operation_id, generation)
            created = _enqueue_restore(backup_id)
            restore_id = created.get("restore_id")
            if (
                not isinstance(restore_id, str)
                or created.get("backup_id") != backup_id
                or created.get("status") != "pending"
            ):
                raise RecoveryRefreshHalted(
                    "restore enqueue result uncertain; intent retained"
                )
            restore_receipt = {
                "backup_id": backup_id,
                "restore_id": restore_id,
                "reconciled_after_intent": False,
                "replayed_enqueue": False,
                "in_place_restore": False,
            }
            _write_new(fd, restore_request, restore_receipt)

        if not isinstance(restore_id, str):
            raise RecoveryRefreshHalted("restore id unavailable")
        restore = _poll(
            _restore_state,
            restore_id,
            operation_id=operation_id,
            generation=generation,
        )
        if (
            restore.get("backup_id") != backup_id
            or restore.get("validated") is not True
            or restore.get("offsite_validated") is not True
            or restore.get("three_d_snapshot_validated") is not True
            or restore.get("offsite_three_d_snapshot_validated") is not True
            or restore.get("checksum_present") is not True
            or restore.get("checksums_match") is not True
            or restore.get("scratch_databases") != 0
            or type(restore.get("size_bytes")) is not int
            or restore["size_bytes"] <= 0
        ):
            raise RecoveryRefreshHalted("restore validation evidence incomplete")
        _parse_time(restore.get("completed_at"), "restore completed_at")
        if _exists(fd, "restore-completed.json"):
            if _read(fd, "restore-completed.json") != restore:
                raise RecoveryRefreshHalted("restore completion receipt differs")
        else:
            _write_new(fd, "restore-completed.json", restore)

        final_authority = _authority(operation_id, generation)
        existing_acceptance = (
            _read(fd, "maintenance-recovery-accepted.json")
            if _exists(fd, "maintenance-recovery-accepted.json")
            else None
        )
        verified_at = (
            existing_acceptance.get("verified_at")
            if existing_acceptance is not None
            else datetime.now(timezone.utc).isoformat()
        )
        if not isinstance(verified_at, str):
            raise RecoveryRefreshHalted("accepted verification timestamp invalid")
        result = {
            "schema": SCHEMA,
            "operation_id": operation_id,
            "generation": generation,
            "authority": final_authority,
            "source": source,
            "backup_id": backup_id,
            "backup_status": "completed",
            "backup_completed_at": backup["completed_at"],
            "backup_size_bytes": backup["size_bytes"],
            "offsite_status": "completed",
            "offsite_encryption_verified": True,
            "restore_id": restore_id,
            "restore_status": "completed",
            "restore_completed_at": restore["completed_at"],
            "restore_validated": True,
            "restore_offsite_validated": True,
            "three_d_snapshot_validated": True,
            "offsite_three_d_snapshot_validated": True,
            "scratch_databases": 0,
            "in_place_restore": False,
            "fresh_recovery_verified": True,
            "full_host_closure": False,
            "production_activation_authorized": False,
            "verified_at": verified_at,
        }
        if existing_acceptance is not None:
            if existing_acceptance != result:
                raise RecoveryRefreshHalted("recovery acceptance receipt differs")
        else:
            _write_new(fd, "maintenance-recovery-accepted.json", result)
        return result
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--journal-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        value = execute(
            operation_id=args.operation_id,
            generation=args.generation,
            journal_root=args.journal_root,
        )
    except (
        RecoveryRefreshHalted,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ):
        print(json.dumps({"status": "FR06_MAINTENANCE_RECOVERY_REFRESH_HALTED"}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
