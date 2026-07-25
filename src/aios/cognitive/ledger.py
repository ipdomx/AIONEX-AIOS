from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import Lock

from .models import DecisionOutcome, Proposal


class DecisionLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, proposal: Proposal, outcome: DecisionOutcome) -> None:
        record = {"proposal": asdict(proposal), "outcome": asdict(outcome)}
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        records: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records
