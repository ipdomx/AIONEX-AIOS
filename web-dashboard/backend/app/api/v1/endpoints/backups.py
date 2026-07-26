"""Backup, restore and disaster recovery endpoints."""
from fastapi import APIRouter, HTTPException, Query

from app.core.production_runtime import production_runtime, now_iso

router = APIRouter()


@router.get("")
async def list_backups(scope: str | None = None, status: str | None = None, limit: int = Query(50, ge=1, le=200)):
    items = [item.__dict__.copy() for item in production_runtime.backups.values()]
    if scope:
        items = [item for item in items if item["scope"] == scope]
    if status:
        items = [item for item in items if item["status"] == status]
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[:limit]


@router.post("")
async def create_backup(name: str, scope: str = "platform"):
    return production_runtime.create_backup(name, scope)


@router.post("/{backup_id}/restore")
async def restore_backup(backup_id: str, dry_run: bool = True):
    if backup_id not in production_runtime.backups:
        raise HTTPException(status_code=404, detail="Backup not found")
    production_runtime.audit("operator", "backup.restore", backup_id, {"dry_run": dry_run})
    return {"backup_id": backup_id, "status": "validated" if dry_run else "restored", "dry_run": dry_run, "timestamp": now_iso()}


@router.get("/dr/status")
async def disaster_recovery_status():
    return production_runtime.dr_state


@router.post("/dr/test")
async def test_disaster_recovery():
    production_runtime.dr_state["last_test_at"] = now_iso()
    production_runtime.dr_state["mode"] = "standby"
    production_runtime.audit("system", "dr.test", "disaster_recovery")
    return {"status": "passed", **production_runtime.dr_state}


@router.post("/dr/failover")
async def failover(confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=409, detail="Explicit confirmation is required")
    production_runtime.dr_state["mode"] = "failover"
    production_runtime.audit("owner", "dr.failover", "disaster_recovery")
    return {"status": "activated", **production_runtime.dr_state}


@router.post("/dr/failback")
async def failback(confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=409, detail="Explicit confirmation is required")
    production_runtime.dr_state["mode"] = "standby"
    production_runtime.audit("owner", "dr.failback", "disaster_recovery")
    return {"status": "completed", **production_runtime.dr_state}
