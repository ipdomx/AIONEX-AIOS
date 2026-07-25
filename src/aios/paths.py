from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def aios_home() -> Path:
    value = os.environ.get("AIOS_HOME")
    home = Path(value) if value else project_root() / "data"
    home.mkdir(parents=True, exist_ok=True)
    return home


def ensure_layout() -> dict[str, Path]:
    home = aios_home()
    paths = {
        "home": home,
        "db": home / "aios.db",
        "projects": home / "projects",
        "workspaces": home / "workspaces",
        "snapshots": home / "snapshots",
        "research": home / "research",
        "updates": home / "updates",
        "logs": home / "logs",
        "backups": home / "backups",
        "plugins": home / "plugins",
    }
    for key, path in paths.items():
        if key != "db":
            path.mkdir(parents=True, exist_ok=True)
    return paths
