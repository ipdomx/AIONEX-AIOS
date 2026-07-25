from __future__ import annotations

import hashlib
from .db import Database


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    def remember(self, content: str, kind: str = 'note', project: str | None = None, source: str | None = None,
                 confidence: float = 1.0, verified: bool = False) -> int:
        confidence = max(0.0, min(1.0, confidence))
        with self.db.connect() as conn:
            cursor = conn.execute(
                'INSERT INTO memories(project, kind, content, source, confidence, verified) VALUES (?, ?, ?, ?, ?, ?)',
                (project, kind, content, source, confidence, int(verified)),
            )
            return int(cursor.lastrowid)

    def search(self, query: str, project: str | None = None, limit: int = 20) -> list[dict]:
        wildcard = f'%{query}%'
        sql = 'SELECT * FROM memories WHERE content LIKE ?'
        params: list[object] = [wildcard]
        if project:
            sql += ' AND project = ?'
            params.append(project)
        sql += ' ORDER BY verified DESC, confidence DESC, id DESC LIMIT ?'
        params.append(limit)
        with self.db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def record_failure(self, description: str, project: str | None = None, failed_solution: str | None = None,
                       successful_solution: str | None = None, verified: bool = False) -> str:
        fingerprint = hashlib.sha256(description.strip().lower().encode()).hexdigest()[:20]
        with self.db.connect() as conn:
            conn.execute(
                '''INSERT INTO failures(project, fingerprint, description, failed_solution, successful_solution, verified)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (project, fingerprint, description, failed_solution, successful_solution, int(verified)),
            )
        return fingerprint

    def find_failures(self, query: str, project: str | None = None) -> list[dict]:
        wildcard = f'%{query}%'
        sql = 'SELECT * FROM failures WHERE description LIKE ?'
        params: list[object] = [wildcard]
        if project:
            sql += ' AND project = ?'
            params.append(project)
        sql += ' ORDER BY verified DESC, id DESC'
        with self.db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
