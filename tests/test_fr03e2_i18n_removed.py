import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web-dashboard" / "frontend"
REMOVED = {"i18next", "react-i18next", "i18next-resources-to-backend"}


def test_unused_i18n_packages_are_not_direct_dependencies() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    dependencies = package.get("dependencies", {})
    assert REMOVED.isdisjoint(dependencies)


def test_frontend_sources_do_not_reference_removed_i18n_packages() -> None:
    ignored = {"node_modules", ".next"}
    suffixes = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
    for path in FRONTEND.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if ignored.intersection(path.parts):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        assert "i18next" not in source.lower(), path
        assert "react-i18next" not in source.lower(), path
