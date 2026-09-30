"""Pinned httpx build contracts. All files are synthetic; no network or process."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "web-dashboard/backend/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("httpx_build_contract_target", SCRIPTS / "build_httpx.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.pop(0)


@pytest.fixture
def locked(tmp_path):
    lock = json.loads((ROOT / "web-dashboard/backend/security-build/httpx/lock.json").read_text())
    for name, body in (("go.mod", "module fixture.invalid/only\n"), ("go.sum", "fixture.invalid/a v1.0.0 h1:fixture\n")):
        p = tmp_path / name
        p.write_text(body)
        lock["files"][name] = m.sha(p)
    (tmp_path / "lock.json").write_text(json.dumps(lock))
    return tmp_path, lock


def test_exact_synthetic_lock_accepted(locked):
    directory, lock = locked
    assert m.read_lock(directory) == lock


@pytest.mark.parametrize("key", ["upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
                                 "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "modules", "expected_binary_sha256"])
def test_missing_field_rejected(locked, key):
    directory, lock = locked
    del lock[key]
    (directory / "lock.json").write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        m.read_lock(directory)


@pytest.mark.parametrize("key,value", [
    ("upstream_version", "1.10.0"), ("local_version", "1.12.0"), ("upstream_commit", "main"),
    ("source_url", "https://example.invalid/untrusted.tar.gz"), ("source_url", "http://codeload.github.com/fixture"),
    ("toolchain_version", "go1.27rc1"), ("toolchain_url", "https://example.invalid/go.tar.gz"),
    ("source_sha256", "f" * 63), ("toolchain_sha256", "F" * 64), ("expected_binary_sha256", None),
])
def test_identity_and_hash_mutation_rejected(locked, key, value):
    directory, lock = locked
    lock[key] = value
    (directory / "lock.json").write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        m.read_lock(directory)


@pytest.mark.parametrize("name", ["go.mod", "go.sum"])
def test_module_file_drift_rejected(locked, name):
    directory, _ = locked
    (directory / name).write_text("different file\n")
    with pytest.raises(ValueError, match="Module lock differs"):
        m.read_lock(directory)


@pytest.mark.parametrize("name", ["go.mod", "go.sum"])
def test_module_symlink_rejected(locked, name):
    directory, _ = locked
    original = directory / name
    copy_path = directory / (name + ".copy")
    original.rename(copy_path)
    original.symlink_to(copy_path)
    with pytest.raises(ValueError, match="Module lock differs"):
        m.read_lock(directory)


def test_extra_linked_module_rejected(locked):
    directory, lock = locked
    lock["modules"]["unexpected.invalid/module"] = "v1.0.0"
    (directory / "lock.json").write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="linked modules"):
        m.read_lock(directory)


def test_floating_module_version_rejected(locked):
    directory, lock = locked
    lock["modules"]["golang.org/x/crypto"] = "latest"
    (directory / "lock.json").write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="linked modules"):
        m.read_lock(directory)


def test_only_version_marker_changes(locked):
    directory, lock = locked
    p = directory / "runner/banner.go"
    p.parent.mkdir()
    original = "package runner\nconst Version = `v1.12.0`\n// Detection code remains.\n"
    p.write_text(original)
    proof = m.label_source(directory, lock)
    assert p.read_text() == original.replace("v1.12.0", "v1.12.0+aios.1")
    assert proof["after_sha256"] == m.sha(p)
    assert proof["before_sha256"] != proof["after_sha256"]


@pytest.mark.parametrize("body", ["package runner\n", "const Version = `v1.11.0`\n", "const Version = `v1.12.0`\n" * 2])
def test_ambiguous_or_changed_version_marker_rejected(locked, body):
    directory, lock = locked
    p = directory / "runner/banner.go"
    p.parent.mkdir()
    p.write_text(body)
    with pytest.raises(ValueError, match="version marker"):
        m.label_source(directory, lock)
    assert p.read_text() == body


def test_upstream_test_scope_is_explicit_not_full_suite_claim():
    commands = m.test_commands("/verified/go")
    assert len(commands) == 3
    assert all(c[:6] == ["/verified/go", "test", "-p=2", "-count=1", "-timeout=60s", "-json"] for c in commands)
    assert commands[1][-2:] == ["-skip", "^TestDo$"]
    assert "./common/authprovider/..." in commands[0]
    assert commands[2][-1].startswith("^(") and commands[2][-1].endswith(")$")
    assert "TestRunner_asn_targets" not in commands[2][-1]
    assert "TestDetermineMostLikelySchemeOrder" in commands[2][-1]


def test_fixed_runtime_builder_is_not_overwritten_by_release_download():
    source = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text()
    installer = (SCRIPTS / "install-security-tools.sh").read_text()
    assert "AS httpx-builder" in source
    assert "COPY scripts/build_httpx.py scripts/build_gitleaks.py /build/" in source
    assert "COPY --from=httpx-builder /build/httpx-output/pd-httpx /usr/local/bin/pd-httpx" in source
    assert "httpx-build-provenance.json" in source
    assert "HTTPX_VERSION=1.12.0" in installer
    assert '"v${HTTPX_VERSION}+aios.1"' in installer
    assert "install_zip_release projectdiscovery/httpx" not in installer
    assert 'mv /usr/local/bin/httpx /usr/local/bin/pd-httpx' not in installer


def test_verifier_exercises_native_app_path_and_loopback():
    source = (SCRIPTS / "verify_security_httpx.py").read_text()
    assert 'ThreadingHTTPServer(("127.0.0.1", 0)' in source
    assert 'asyncio.run(_run_network_tool(' in source
    assert 'application_result["findings"] == []' in source
    assert '"external_network": False' in source
    assert '"full_image_security_passed": False' in source


def test_pinned_source_compiler_and_no_checksum_bypass():
    source = (SCRIPTS / "build_httpx.py").read_text()
    assert '"GOTOOLCHAIN": "local"' in source and '"GOSUMDB": "sum.golang.org"' in source
    assert '"GOFLAGS": "-mod=readonly"' in source
    assert '"GOSUMDB": "off"' not in source
    assert 'sha(binary) != lock["expected_binary_sha256"]' in source
    assert 'original_sums <= completed_sums' in source


def test_real_lock_is_stable_and_preserves_test_selection():
    directory = ROOT / "web-dashboard/backend/security-build/httpx"
    lock = m.read_lock(directory)
    before = copy.deepcopy(lock)
    m.test_commands("go")
    assert lock == before
    assert lock["toolchain_version"] == "go1.27.1"
    assert lock["modules"]["golang.org/x/crypto"] == "v0.55.0"
