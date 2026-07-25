from __future__ import annotations

import uuid
from .db import Database


class ApprovalManager:
    def __init__(self, db: Database):
        self.db = db

    def request(self, summary: str, project: str | None = None) -> str:
        action_id = uuid.uuid4().hex[:16]
        with self.db.connect() as conn:
            conn.execute(
                'INSERT INTO approvals(action_id, project, summary) VALUES (?, ?, ?)',
                (action_id, project, summary),
            )
        return action_id

    def decide(self, action_id: str, approved: bool) -> None:
        status = 'approved' if approved else 'rejected'
        with self.db.connect() as conn:
            conn.execute(
                'UPDATE approvals SET status = ?, decided_at = CURRENT_TIMESTAMP WHERE action_id = ?',
                (status, action_id),
            )
