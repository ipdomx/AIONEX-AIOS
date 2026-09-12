import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web-dashboard" / "frontend"
REMOVED = {"react-window", "@types/react-window"}


def test_unused_react_window_packages_are_not_direct_dependencies() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    assert REMOVED.isdisjoint(package.get("dependencies", {}))
    assert REMOVED.isdisjoint(package.get("devDependencies", {}))
    assert REMOVED.isdisjoint(lock["packages"][""].get("dependencies", {}))
    assert REMOVED.isdisjoint(lock["packages"][""].get("devDependencies", {}))


def test_frontend_sources_do_not_reference_react_window() -> None:
    ignored = {"node_modules", ".next"}
    suffixes = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
    for path in FRONTEND.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if ignored.intersection(path.parts):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        assert "react-window" not in source.lower(), path
