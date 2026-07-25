from __future__ import annotations

import importlib
from .db import Database


class PluginRegistry:
    def __init__(self, db: Database):
        self.db = db

    def register(self, name: str, version: str, module: str) -> None:
        importlib.import_module(module)
        with self.db.connect() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO plugins(name, version, module, enabled) VALUES (?, ?, ?, 1)',
                (name, version, module),
            )

    def list(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute('SELECT * FROM plugins ORDER BY name').fetchall()
        return [dict(row) for row in rows]
