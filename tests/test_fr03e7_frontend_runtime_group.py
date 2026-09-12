import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web-dashboard" / "frontend"


def test_postcss_direct_dependency_matches_override() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["postcss"] == package["overrides"]["postcss"] == "8.5.28"


def test_frontend_runtime_group_resolves_expected_versions() -> None:
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    assert packages["node_modules/postcss"]["version"] == "8.5.28"
    assert packages["node_modules/posthog-js"]["version"] == "1.428.8"
    assert packages["node_modules/react-hook-form"]["version"] == "7.87.0"
