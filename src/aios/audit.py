from __future__ import annotations

import json
from .db import Database


class AuditJournal:
    def __init__(self, db: Database):
        self.db = db

    def record(self, actor: str, action: str, result: str, target: str | None = None, details: dict | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                'INSERT INTO audit_events(actor, action, target, result, details) VALUES (?, ?, ?, ?, ?)',
                (actor, action, target, result, json.dumps(details or {}, ensure_ascii=False)),
            )

    def recent(self, limit: int = 20) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                'SELECT * FROM audit_events ORDER BY id DESC LIMIT ?',
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
