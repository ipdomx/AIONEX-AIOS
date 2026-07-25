from __future__ import annotations
import hashlib, time, uuid
from pathlib import Path
from .backup import BackupManager


class DisasterRecoveryManager:
    def __init__(self, backup_manager: BackupManager):
        self.backup_manager = backup_manager
        self.operations = {}

    async def restore(self, backup_id: str, destination: str) -> dict:
        operation_id = uuid.uuid4().hex
        started = time.time()
        status, error = "SUCCESS", None
        try:
            await self.backup_manager.restore_backup(backup_id, destination)
        except Exception as exc:
            status, error = "FAILED", str(exc)
        result = {"operation_id": operation_id, "backup_id": backup_id, "destination": destination,
                  "status": status, "error": error, "duration_seconds": time.time()-started}
        self.operations[operation_id] = result
        return result

    async def summary(self) -> dict:
        values = list(self.operations.values())
        return {"total_operations": len(values), "successful": sum(v["status"]=="SUCCESS" for v in values),
                "failed": sum(v["status"]=="FAILED" for v in values)}


class RecoveryValidator:
    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def validate(self, backup_path: str, restored_path: str) -> dict:
        source, target = Path(backup_path), Path(restored_path)
        errors, checked = [], 0
        for file in source.rglob("*"):
            if not file.is_file():
                continue
            checked += 1
            other = target / file.relative_to(source)
            if not other.exists():
                errors.append(f"missing:{file.relative_to(source)}")
            elif self._hash(file) != self._hash(other):
                errors.append(f"checksum:{file.relative_to(source)}")
        return {"valid": not errors, "checked_files": checked, "errors": errors}
