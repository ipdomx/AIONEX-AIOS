from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .db import Database
from .paths import ensure_layout


class ProjectRegistry:
    def __init__(self, db: Database):
        self.db = db

    def add(self, name: str, path: str, language: str | None = None) -> None:
        project_path = Path(path).expanduser().resolve()
        if not project_path.exists():
            raise FileNotFoundError(f'Project path not found: {project_path}')
        with self.db.connect() as conn:
            conn.execute(
                'INSERT INTO projects(name, path, language) VALUES (?, ?, ?)',
                (name, str(project_path), language),
            )

    def get(self, name: str) -> dict:
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM projects WHERE name = ?', (name,)).fetchone()
        if row is None:
            raise KeyError(f'Unknown project: {name}')
        return dict(row)

    def list(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute('SELECT * FROM projects ORDER BY name').fetchall()
        return [dict(row) for row in rows]

    def create_workspace(self, name: str) -> Path:
        project = self.get(name)
        source = Path(project['path'])
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        target = ensure_layout()['workspaces'] / f'{name}-{stamp}'
        ignore = shutil.ignore_patterns('.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build')
        shutil.copytree(source, target, ignore=ignore)
        return target
