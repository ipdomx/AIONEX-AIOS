from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any


class AIInteractionJournal:
    """Append-only hash chained ledger for routed model interactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def append(self, event: dict[str, Any]) -> str:
        with self._lock:
            previous = self._last_hash()
            payload = dict(event)
            payload["previous_hash"] = previous
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            payload["event_hash"] = digest
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            return digest

    def verify(self) -> bool:
        previous = ""
        if not self.path.exists():
            return True
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            digest = payload.pop("event_hash", "")
            if payload.get("previous_hash", "") != previous:
                return False
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if digest != expected:
                return False
            previous = digest
        return True

    def _last_hash(self) -> str:
        if not self.path.exists():
            return ""
        lines = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return json.loads(lines[-1]).get("event_hash", "") if lines else ""
