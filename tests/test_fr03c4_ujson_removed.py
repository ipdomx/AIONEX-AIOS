from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_unused_ujson_is_not_a_direct_backend_runtime_dependency() -> None:
    requirements = (ROOT / "web-dashboard/backend/requirements-runtime.txt").read_text(
        encoding="utf-8"
    )
    assert not any(
        line.strip().lower().startswith("ujson")
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

    production_python = ROOT / "web-dashboard/backend/app"
    references: list[str] = []
    for path in production_python.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import ujson" in text or "from ujson" in text:
            references.append(str(path.relative_to(ROOT)))
    assert references == []
