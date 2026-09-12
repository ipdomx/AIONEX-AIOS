import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web-dashboard" / "frontend"


def test_dashboard_does_not_declare_zustand_directly() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    assert "zustand" not in package["dependencies"]
    assert "zustand" not in lock["packages"][""]["dependencies"]


def test_reactflow_retains_its_zustand_dependency() -> None:
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    core = lock["packages"]["node_modules/@reactflow/core"]
    assert core["dependencies"]["zustand"] == "^4.4.1"
    assert "node_modules/zustand" in lock["packages"]
