import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web-dashboard/frontend"


def test_date_fns_is_not_a_direct_or_locked_dependency() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    assert "date-fns" not in package.get("dependencies", {})
    assert "date-fns" not in lock["packages"][""].get("dependencies", {})
    assert "node_modules/date-fns" not in lock["packages"]


def test_frontend_source_does_not_import_date_fns() -> None:
    roots = [FRONTEND / "src", FRONTEND / "scripts"]
    suffixes = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
    corpus = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                corpus.append(path.read_text(encoding="utf-8", errors="ignore"))
    assert "date-fns" not in "\n".join(corpus)
