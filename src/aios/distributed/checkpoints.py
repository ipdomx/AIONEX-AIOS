from __future__ import annotations
import asyncio, hashlib, json, time, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

@dataclass
class CheckpointRecord:
    checkpoint_id: str
    task_id: str
    sequence: int
    path: str
    checksum: str
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

class CheckpointManager:
    def __init__(self, root: str = "storage/checkpoints"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.records: Dict[str, list[CheckpointRecord]] = {}
        self.lock = asyncio.Lock()

    async def save(self, task_id: str, state: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> CheckpointRecord:
        async with self.lock:
            sequence = len(self.records.get(task_id, [])) + 1
            checkpoint_id = uuid.uuid4().hex
            task_dir = self.root / task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            path = task_dir / f"{sequence:08d}-{checkpoint_id}.json"
            payload = {"task_id": task_id, "sequence": sequence, "state": state, "metadata": metadata or {}, "created_at": time.time()}
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            path.write_bytes(encoded)
            record = CheckpointRecord(checkpoint_id, task_id, sequence, str(path), hashlib.sha256(encoded).hexdigest(), metadata=metadata or {})
            self.records.setdefault(task_id, []).append(record)
            return record

    async def latest(self, task_id: str) -> Optional[CheckpointRecord]:
        async with self.lock:
            records = self.records.get(task_id, [])
            return records[-1] if records else None

    async def load(self, checkpoint_id: str) -> Dict[str, Any]:
        async with self.lock:
            record = next((item for records in self.records.values() for item in records if item.checkpoint_id == checkpoint_id), None)
            if record is None:
                raise KeyError(checkpoint_id)
            raw = Path(record.path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != record.checksum:
                raise ValueError("checkpoint checksum mismatch")
            return json.loads(raw.decode("utf-8"))

    async def prune(self, task_id: str, keep: int = 3) -> int:
        async with self.lock:
            records = self.records.get(task_id, [])
            stale = records[:-max(0, keep)] if keep else list(records)
            self.records[task_id] = records[-keep:] if keep else []
            for record in stale:
                Path(record.path).unlink(missing_ok=True)
            return len(stale)
