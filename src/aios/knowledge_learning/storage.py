from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Iterable


class HashChainedJsonl:
    """Append-only JSONL storage with a hash chain for tamper evidence."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def _digest(payload: dict, previous_hash: str) -> str:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{previous_hash}:{body}".encode("utf-8")).hexdigest()

    def append(self, payload: dict) -> dict:
        with self._lock:
            previous_hash = "GENESIS"
            if self.path.exists():
                lines = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if lines:
                    previous_hash = json.loads(lines[-1])["record_hash"]
            record = {"payload": payload, "previous_hash": previous_hash}
            record["record_hash"] = self._digest(payload, previous_hash)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            return record

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def payloads(self) -> Iterable[dict]:
        for record in self.read():
            yield record["payload"]

    def verify(self) -> bool:
        previous_hash = "GENESIS"
        for record in self.read():
            if record.get("previous_hash") != previous_hash:
                return False
            if record.get("record_hash") != self._digest(record.get("payload", {}), previous_hash):
                return False
            previous_hash = record["record_hash"]
        return True
