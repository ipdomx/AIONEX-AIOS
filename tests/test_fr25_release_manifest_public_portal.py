"""FR25 source-only release inventory must identify the public portal.

The existing schema-1 and exact FR24 recovery compose fields are preserved.
The test neither connects to Docker nor reads any production secrets.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/generate_production_release_manifest.py"


def _module():
    spec = importlib.util.spec_from_file_location("aionex_fr25_release_manifest", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean_git(command: str, *arguments: str) -> str:
    assert command == "git"
    if arguments == ("rev-parse", "HEAD"):
        return "a" * 40
    if arguments == ("status", "--porcelain"):
        return ""
    raise AssertionError("unexpected or mutable Git call")


def test_source_manifest_preserves_recovery_contract_and_counts_public_portal(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "_run", _clean_git)
    manifest = module.source_manifest()
    portal = json.loads((ROOT / "vip-frontend/package.json").read_text(encoding="utf-8"))
    owner = json.loads(
        (ROOT / "web-dashboard/frontend/package.json").read_text(encoding="utf-8")
    )
    assert manifest["schemaVersion"] == 1
    assert manifest["sourceCommit"] == "a" * 40
    assert manifest["sourceTreeClean"] is True
    assert manifest["components"]["ownerFrontend"] == owner["version"]
    assert manifest["components"]["publicPortal"] == portal["version"]
    assert manifest["components"]["publicPortal"] == "1.6.0"
    assert manifest["components"]["backend"]
    assert manifest["components"]["android"]
    assert manifest["components"]["ios"]
    assert set(manifest["compose"]) == {"webDashboardSha256", "deploySha256"}
    assert all(len(digest) == 64 for digest in manifest["compose"].values())


def test_public_portal_version_missing_fails_closed(monkeypatch, tmp_path):
    module = _module()
    original_read = module.ROOT
    temporary = tmp_path / "source"
    temporary.mkdir()
    import shutil
    for name in ("pyproject.toml",):
        shutil.copy2(ROOT / name, temporary / name)
    for parent in (
        "web-dashboard/frontend",
        "vip-frontend",
        "web-dashboard/backend/app/core",
        "mobile/android/app",
        "mobile/ios",
        "web-dashboard",
        "deploy/production",
    ):
        (temporary / parent).mkdir(parents=True, exist_ok=True)
    files = (
        "web-dashboard/frontend/package.json",
        "vip-frontend/package.json",
    )
    for name in files:
        target = temporary / name
        target.write_bytes((ROOT / name).read_bytes())
    invalid = json.loads((temporary / "vip-frontend/package.json").read_text())
    invalid.pop("version")
    (temporary / "vip-frontend/package.json").write_text(json.dumps(invalid))
    monkeypatch.setattr(module, "ROOT", temporary)
    monkeypatch.setattr(module, "_run", _clean_git)
    with pytest.raises(RuntimeError, match="public portal version"):
        module.source_manifest()
    assert module.ROOT == temporary
    assert original_read == ROOT


def test_fr24_recovery_contract_accepts_extra_public_portal_component():
    """Extending components must not mutate the strict schema-1 recovery shape."""
    path = ROOT / "scripts/recovery/fr24_restore_plan.py"
    spec = importlib.util.spec_from_file_location("aionex_fr24_recovery_validator", path)
    assert spec is not None and spec.loader is not None
    recovery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recovery)
    fixture = json.loads((ROOT / "tests/fixtures/fr24/recovery_manifest.json").read_text())
    original = fixture["release"]
    revised = json.loads(json.dumps(original))
    revised["components"]["publicPortal"] = "1.6.0"
    assert recovery._validate_release(revised) == revised
    assert set(revised) == set(original)
    assert set(revised["compose"]) == set(original["compose"])
