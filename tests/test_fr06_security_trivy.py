"""Trivy source-lock and bounded-build contracts; synthetic input only."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "web-dashboard/backend/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("trivy_build_contract", SCRIPTS / "build_trivy.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.pop(0)


@pytest.fixture
def locked(tmp_path):
    folder = tmp_path / "lock"
    shutil.copytree(ROOT / "web-dashboard/backend/security-build/trivy", folder)
    value = json.loads((folder / "lock.json").read_text())
    return folder, value


def test_actual_pinned_lock_accepted(locked):
    folder, value = locked
    assert m.read_lock(folder) == value
    assert value["modules"]["google.golang.org/grpc"] == "v1.83.2"


@pytest.mark.parametrize("field", ["upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
                                  "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "upstream_files",
                                  "modules", "expected_binary_sha256"])
def test_incomplete_lock_rejected(locked, field):
    folder, value = locked
    del value[field]
    (folder / "lock.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.read_lock(folder)


@pytest.mark.parametrize("field,invalid", [("upstream_version", "0.73.0"), ("local_version", "0.74.0"),
    ("upstream_commit", "main"), ("source_url", "https://example.invalid/input"),
    ("source_sha256", "f" * 63), ("toolchain_version", "go1.26.6"), ("toolchain_url", "http://go.dev/compiler"),
    ("toolchain_sha256", None), ("expected_binary_sha256", "F" * 64), ("modules", {}), ("upstream_files", {})])
def test_unreviewed_inputs_rejected(locked, field, invalid):
    folder, value = locked
    value[field] = invalid
    (folder / "lock.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.read_lock(folder)


@pytest.mark.parametrize("name", ["go.mod", "go.sum"])
@pytest.mark.parametrize("fault", ["contents", "symlink"])
def test_locked_module_drift_rejected(locked, name, fault):
    folder, _ = locked
    p = folder / name
    if fault == "contents":
        p.write_text("unreviewed module input")
    else:
        retained = p.with_suffix(p.suffix + ".original")
        p.rename(retained)
        p.symlink_to(retained)
    with pytest.raises(ValueError):
        m.read_lock(folder)


def test_old_grpc_rejected_even_with_other_valid_fields(locked):
    folder, value = locked
    value["modules"]["google.golang.org/grpc"] = "v1.82.1"
    (folder / "lock.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.read_lock(folder)


def test_lock_symlink_rejected(locked):
    folder, _ = locked
    (folder / "lock.json").rename(folder / "original.json")
    (folder / "lock.json").symlink_to(folder / "original.json")
    with pytest.raises(ValueError):
        m.read_lock(folder)


@pytest.mark.parametrize("fault", [None, "old-first", "old-second", "new-first", "new-second"])
def test_dependency_patch_validates_all_inputs_before_writes(tmp_path, fault):
    source, replacement = tmp_path / "source", tmp_path / "replacement"
    source.mkdir()
    replacement.mkdir()
    lock = {"upstream_files": {}, "files": {}}
    for name in ["go.mod", "go.sum"]:
        (source / name).write_text("original " + name)
        (replacement / name).write_text("corrected " + name)
        lock["upstream_files"][name] = m.sha(source / name)
        lock["files"][name] = m.sha(replacement / name)
    if fault:
        side, ordinal = fault.split("-")
        root = source if side == "old" else replacement
        (root / ("go.mod" if ordinal == "first" else "go.sum")).write_text("unexpected")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    if fault:
        with pytest.raises(ValueError):
            m.prepare_modules(source, replacement, lock)
        assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    else:
        m.prepare_modules(source, replacement, lock)
        assert all(m.sha(source / n) == h for n, h in lock["files"].items())


def test_compiler_environment_overrides_unsafe_inherited_settings(monkeypatch):
    monkeypatch.setenv("GOSUMDB", "off")
    monkeypatch.setenv("GOTOOLCHAIN", "auto")
    env = m.build_environment(Path("/verified"))
    assert env["GOTOOLCHAIN"] == "local" and env["GOSUMDB"] == "sum.golang.org"
    assert env["GOFLAGS"] == "-mod=readonly" and env["CGO_ENABLED"] == "0"
    assert env["GOEXPERIMENT"] == "jsonv2"
    assert env["GONOSUMDB"] == env["GOPRIVATE"] == env["GONOPROXY"] == ""


def test_reproducible_local_version_flags(locked):
    _, lock = locked
    command = m.build_command("go", Path("/owned/trivy"), lock)
    assert "-trimpath" in command and "-buildvcs=false" in command
    assert command[-1] == "./cmd/trivy"
    assert "app.ver=0.74.0+aios.1" in command[command.index("-ldflags") + 1]


def test_selected_scope_covers_real_detectors_and_not_all_upstream():
    assert len(m.TEST_PACKAGES) == 7
    assert "./pkg/detector/library" in m.TEST_PACKAGES and "./pkg/db" in m.TEST_PACKAGES
    assert "./pkg/fanal/analyzer/secret" in m.TEST_PACKAGES
    assert '"all_upstream_tests_claimed": False' in (SCRIPTS / "build_trivy.py").read_text()


def test_runtime_preserves_native_trivy_and_all_scanner_modes():
    dockerfile = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text()
    installer = (SCRIPTS / "install-security-tools.sh").read_text()
    verifier = (SCRIPTS / "verify_security_trivy.py").read_text()
    assert "AS trivy-builder" in dockerfile and "--from=trivy-builder /build/trivy-output/trivy /usr/local/bin/trivy" in dockerfile
    assert "trivy-build-provenance.json" in dockerfile and "TRIVY-LICENSE" in dockerfile
    assert "TRIVY_VERSION=0.74.0" in installer
    assert '"${TRIVY_VERSION}+aios.1"' in installer
    assert "trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" not in installer
    assert '_command_for("trivy", root)' in verifier and '_run_source_tool("trivy", root' in verifier
    assert "default_secret_rules_not_disabled" in verifier
    assert "incompatible_and_missing_db_rejected" in verifier
    assert "fixture_database_not_current_public_feed" in verifier
