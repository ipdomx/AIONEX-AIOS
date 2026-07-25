from __future__ import annotations

import hashlib
from .db import Database


class DurableMemory:
    """Deduplicated, revisable and auditable long-term memory."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def fingerprint(content: str, kind: str, project: str | None) -> str:
        raw = f'{project or "global"}|{kind}|{content.strip().lower()}'
        return hashlib.sha256(raw.encode()).hexdigest()

    def remember_once(self, content: str, kind: str = 'knowledge', project: str | None = None,
                      source: str | None = None, confidence: float = 1.0, verified: bool = False) -> int:
        fp = self.fingerprint(content, kind, project)
        marker = f'fingerprint:{fp}'
        with self.db.connect() as conn:
            row = conn.execute('SELECT id FROM memories WHERE source = ?', (marker,)).fetchone()
            if row:
                return int(row['id'])
            cursor = conn.execute(
                '''INSERT INTO memories(project, kind, content, source, confidence, verified)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (project, kind, content, marker, max(0.0, min(1.0, confidence)), int(verified)),
            )
            return int(cursor.lastrowid)

    def revise(self, memory_id: int, new_content: str, reason: str) -> None:
        with self.db.connect() as conn:
            row = conn.execute('SELECT content FROM memories WHERE id = ?', (memory_id,)).fetchone()
            if row is None:
                raise KeyError(f'Unknown memory: {memory_id}')
            conn.execute(
                'INSERT INTO memory_revisions(memory_id, previous_content, new_content, reason) VALUES (?, ?, ?, ?)',
                (memory_id, row['content'], new_content, reason),
            )
            conn.execute('UPDATE memories SET content = ?, verified = 0 WHERE id = ?', (new_content, memory_id))
