from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json

from .models import SecurityAssessment


class SecurityLedger:
    """Append-only hash-chained assessment ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, assessment: SecurityAssessment) -> str:
        previous = self._last_hash()
        body = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous,
            "assessment": asdict(assessment),
        }
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        record_hash = sha256(encoded).hexdigest()
        body["record_hash"] = record_hash
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str) + "\n")
        return record_hash

    def verify(self) -> bool:
        previous = "GENESIS"
        if not self.path.exists():
            return True
        for line in self.path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            record_hash = record.pop("record_hash")
            if record.get("previous_hash") != previous:
                return False
            encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
            if sha256(encoded).hexdigest() != record_hash:
                return False
            previous = record_hash
        return True

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "GENESIS"
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1])["record_hash"] if lines else "GENESIS"
