"""Prepare bounded isolated source copies for Security Lab remediation agents."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, or_, select

from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AuditEvent, SecurityFinding, SecurityRemediation, SecurityTarget

logger = get_logger(__name__)
SOURCE_ROOT = Path("/var/lib/aionex/security-sources")
WORK_ROOT = Path("/var/lib/aionex/security-remediations")
_SKIP = {".git", "node_modules", "vendor", ".venv", "venv", ".next", "dist", "build", "coverage"}


def now() -> datetime:
    return datetime.now(UTC)


def _copy_source(source: Path, destination: Path, *, max_files: int = 25_000, max_bytes: int = 1_073_741_824) -> dict:
    source = source.resolve(strict=True); root = SOURCE_ROOT.resolve(strict=True)
    if source != root and root not in source.parents:
        raise ValueError("Remediation source is outside the Security Lab source root")
    if destination.exists():
        raise FileExistsError("Remediation worktree already exists")
    destination.mkdir(parents=True, mode=0o700)
    files = 0; total = 0; digest = hashlib.sha256()
    try:
        for path in source.rglob("*"):
            relative = path.relative_to(source)
            if any(part in _SKIP for part in relative.parts):
                continue
            if path.is_symlink():
                continue
            target = destination / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700); continue
            if not path.is_file(): continue
            files += 1; size = path.stat().st_size; total += size
            if files > max_files or total > max_bytes:
                raise ValueError("Remediation source exceeds isolation limits")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, target, follow_symlinks=False)
            os.chmod(target, 0o600)
            digest.update(relative.as_posix().encode()); digest.update(str(size).encode())
    except Exception:
        shutil.rmtree(destination, ignore_errors=True); raise
    return {"files": files, "bytes": total, "manifest_digest": digest.hexdigest()}


class Worker:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event(); self.cycles = 0; self.errors = 0
        self.health = Path(os.getenv("SECURITY_REMEDIATION_WORKER_HEALTH_FILE", "/tmp/aionex-security-remediation-worker.json"))
        self.poll = max(1, int(os.getenv("SECURITY_REMEDIATION_WORKER_POLL_SECONDS", "5")))

    def write_health(self, status: str) -> None:
        payload = {"status": status, "checked_at": now().isoformat(), "checked_at_epoch": time.time(), "cycles": self.cycles, "errors": self.errors, "secret_returned": False}
        self.health.parent.mkdir(parents=True, exist_ok=True); tmp = self.health.with_name("." + self.health.name + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8"); os.chmod(tmp, 0o600); os.replace(tmp, self.health)

    async def claim(self) -> tuple[str, str] | None:
        stale = now() - timedelta(minutes=30)
        async with SessionLocal() as session:
            item = await session.scalar(select(SecurityRemediation).where(or_(SecurityRemediation.status == "planned", and_(SecurityRemediation.status == "preparing", SecurityRemediation.updated_at < stale))).order_by(SecurityRemediation.created_at).with_for_update(skip_locked=True).limit(1))
            if item is None: return None
            token = str(uuid4()); item.status = "preparing"; item.worktree_ref = f"preparing:{token}"
            await session.commit(); return item.id, token

    async def prepare(self, remediation_id: str, token: str) -> None:
        async with SessionLocal() as session:
            item = await session.scalar(select(SecurityRemediation).where(SecurityRemediation.id == remediation_id, SecurityRemediation.status == "preparing", SecurityRemediation.worktree_ref == f"preparing:{token}").with_for_update())
            if item is None: return
            finding = await session.get(SecurityFinding, item.finding_id)
            target = await session.get(SecurityTarget, finding.target_id) if finding else None
            if finding is None or target is None or target.project_id != item.project_id:
                raise RuntimeError("Remediation source target is invalid")
            raw = str((target.target_metadata or {}).get("source_snapshot") or "").strip()
            if not raw: raise RuntimeError("Managed target has no isolated source snapshot")
            source = Path(raw); destination = WORK_ROOT / item.id / "source"
            evidence = await asyncio.to_thread(_copy_source, source, destination)
            plan_path = destination.parent / "remediation-plan.json"
            plan_path.write_text(json.dumps(item.plan, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"); os.chmod(plan_path, 0o600)
            item.worktree_ref = f"security-remediation://{item.id}/source"
            item.status = "worktree_ready"
            item.regression_result = {"isolation": evidence, "production_modified": False}
            session.add(AuditEvent(organization_id=item.organization_id, user_id=item.requested_by_id, action="security.remediation.worktree_ready", resource_type="security_remediation", resource_id=item.id, details={**evidence, "production_modified": False}))
            await session.commit()

    async def run(self) -> None:
        WORK_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700); self.write_health("healthy")
        while not self.stop_event.is_set():
            self.cycles += 1
            try:
                claimed = await self.claim()
                if claimed: await self.prepare(*claimed)
                self.write_health("healthy")
            except Exception:
                self.errors += 1; logger.exception("Security remediation worker cycle failed"); self.write_health("degraded")
            try: await asyncio.wait_for(self.stop_event.wait(), timeout=self.poll)
            except TimeoutError: pass

    def stop(self) -> None: self.stop_event.set()


def healthcheck() -> int:
    path = Path(os.getenv("SECURITY_REMEDIATION_WORKER_HEALTH_FILE", "/tmp/aionex-security-remediation-worker.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8")); return 0 if data.get("status") in {"healthy", "degraded"} and time.time() - float(data["checked_at_epoch"]) < 90 else 1
    except Exception: return 1


async def _main() -> None:
    setup_logging(); worker = Worker(); loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError: pass
    await worker.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--healthcheck", action="store_true"); args = parser.parse_args()
    raise SystemExit(healthcheck()) if args.healthcheck else asyncio.run(_main())
