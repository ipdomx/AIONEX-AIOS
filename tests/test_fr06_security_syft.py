"""Source-lock/archive and offline-scope contracts; all inputs are synthetic."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "web-dashboard/backend/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("syft_build_contract_target", SCRIPTS / "build_syft.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
finally:
    sys.path.pop(0)


@pytest.fixture
def locked(tmp_path):
    value = json.loads((ROOT / "web-dashboard/backend/security-build/syft/lock.json").read_text())
    for n in ("go.mod", "go.sum"):
        p = tmp_path / n; p.write_text("synthetic module input\n"); value["files"][n] = m.sha(p)
    (tmp_path / "lock.json").write_text(json.dumps(value))
    return tmp_path, value


def test_exact_lock_and_real_repository_lock_accepted(locked):
    folder, value = locked
    assert m.read_lock(folder) == value
    real = m.read_lock(ROOT / "web-dashboard/backend/security-build/syft")
    assert real["toolchain_version"] == "go1.27.1"
    assert real["modules"]["golang.org/x/crypto"] == "v0.56.0"


@pytest.mark.parametrize("field", ["upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
                                  "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "modules",
                                  "build_date", "expected_binary_sha256"])
def test_missing_fields_rejected(locked, field):
    folder, value = locked; del value[field]; (folder / "lock.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.read_lock(folder)


@pytest.mark.parametrize("field,value", [("upstream_version", "1.50.0"), ("local_version", "1.52.0"),
    ("upstream_commit", "main"), ("source_url", "https://example.invalid/source.tgz"),
    ("toolchain_url", "http://go.dev/toolchain"), ("toolchain_version", "go1.27rc1"),
    ("source_sha256", "a" * 63), ("toolchain_sha256", "A" * 64),
    ("expected_binary_sha256", None), ("build_date", "now")])
def test_unpinned_identity_rejected(locked, field, value):
    folder, lock = locked; lock[field] = value; (folder / "lock.json").write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        m.read_lock(folder)


@pytest.mark.parametrize("file", ["go.mod", "go.sum"])
@pytest.mark.parametrize("change", ["content", "symlink"])
def test_module_file_drift_rejected(locked, file, change):
    folder, _ = locked; p = folder / file
    if change == "content":
        p.write_text("changed")
    else:
        other = folder / "other"; p.rename(other); p.symlink_to(other)
    with pytest.raises(ValueError):
        m.read_lock(folder)


def fixture_archive(tmp_path, *, extra=None, omit=None, changed_link=False):
    path = tmp_path / "source.tgz"
    with tarfile.open(path, "w:gz") as t:
        def regular(n, data):
            member = tarfile.TarInfo(n); member.size = len(data); t.addfile(member, io.BytesIO(data))
        regular("source/main.go", b"package main\n")
        for name, target in m.OMITTED_LINKS.items():
            if name == omit:
                continue
            info = tarfile.TarInfo("source/" + name); info.type = tarfile.SYMTYPE
            info.linkname = "/unrecognized" if changed_link else target; t.addfile(info)
        if extra:
            name, kind, target = extra
            info = tarfile.TarInfo(name); info.type = kind; info.linkname = target
            if kind == tarfile.REGTYPE:
                info.size = 1; t.addfile(info, io.BytesIO(b"x"))
            else:
                t.addfile(info)
    return path


def test_absolute_fixtures_are_recorded_but_never_materialized(tmp_path):
    a = fixture_archive(tmp_path); dest = tmp_path / "out"
    root = m.extract_source(a, m.sha(a), dest)
    assert (root / "main.go").read_bytes() == b"package main\n"
    for relative in m.OMITTED_LINKS:
        assert not (root / relative).exists() and not (root / relative).is_symlink()


@pytest.mark.parametrize("extra", [("source/../../escape", tarfile.REGTYPE, ""),
    ("/absolute", tarfile.REGTYPE, ""), ("source/main.go", tarfile.REGTYPE, ""),
    ("source/link", tarfile.SYMTYPE, "/etc/passwd"), ("source/link", tarfile.SYMTYPE, "../../outside"),
    ("source/hard", tarfile.LNKTYPE, "source/main.go"), ("source/device", tarfile.CHRTYPE, "")])
def test_extra_unsafe_archive_entries_never_extract(tmp_path, extra):
    a = fixture_archive(tmp_path, extra=extra)
    with pytest.raises(ValueError):
        m.extract_source(a, m.sha(a), tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("fault", ["hash", "source-symlink", "missing-fixture", "changed-fixture"])
def test_fixture_set_and_input_integrity_required(tmp_path, fault):
    a = fixture_archive(tmp_path, omit=next(iter(m.OMITTED_LINKS)) if fault == "missing-fixture" else None,
                        changed_link=fault == "changed-fixture")
    digest = m.sha(a)
    if fault == "hash":
        digest = "0" * 64
    if fault == "source-symlink":
        link = tmp_path / "alias"; link.symlink_to(a); a = link
    with pytest.raises(ValueError):
        m.extract_source(a, digest, tmp_path / "out")


def test_existing_extraction_is_not_replaced(tmp_path):
    a = fixture_archive(tmp_path); out = tmp_path / "out"; out.mkdir(); sentinel = out / "retained"; sentinel.write_text("unchanged")
    with pytest.raises(ValueError):
        m.extract_source(a, m.sha(a), out)
    assert sentinel.read_text() == "unchanged"


def test_environment_locks_toolchain_and_checksum_database(monkeypatch):
    monkeypatch.setenv("GOSUMDB", "off"); monkeypatch.setenv("GOTOOLCHAIN", "auto")
    env = m.build_environment(Path("/verified"))
    assert env["GOSUMDB"] == "sum.golang.org" and env["GOTOOLCHAIN"] == "local"
    assert env["GOFLAGS"] == "-mod=readonly" and env["CGO_ENABLED"] == "0"
    assert env["GONOSUMDB"] == env["GOPRIVATE"] == env["GONOPROXY"] == ""


def test_local_identity_and_reproducible_flags(locked):
    _, lock = locked; command = m.build_command("go", Path("/owned/syft"), lock)
    assert "-trimpath" in command and "-buildvcs=false" in command
    flags = command[command.index("-ldflags") + 1]
    assert "main.version=1.52.0+aios.1" in flags and lock["upstream_commit"] in flags
    assert command[-1] == "./cmd/syft"


def test_scope_is_selected_and_image_daemon_not_requested():
    assert len(m.TEST_PACKAGES) == 6 and len(m.EXTERNAL_TESTS) == 6
    assert "TestDpkgArchiveCataloger" in m.EXTERNAL_TESTS
    assert "./syft/internal/fileresolver" not in m.TEST_PACKAGES
    source = (SCRIPTS / "build_syft.py").read_text()
    assert '"all_upstream_tests_claimed": False' in source
    assert "docker.sock" not in source


def test_docker_builder_and_runtime_do_not_install_rejected_official_binary():
    dockerfile = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text()
    installer = (SCRIPTS / "install-security-tools.sh").read_text()
    assert "AS syft-builder" in dockerfile and "--from=syft-builder /build/syft-output/syft /usr/local/bin/syft" in dockerfile
    assert "syft-build-provenance.json" in dockerfile and "SYFT-LICENSE" in dockerfile
    assert "SYFT_VERSION=1.52.0" in installer and '"${SYFT_VERSION}+aios.1"' in installer
    assert "install_tgz_release anchore/syft" not in installer


def test_native_verifier_covers_inventory_not_fake_vulnerabilities():
    source = (SCRIPTS / "verify_security_syft.py").read_text()
    for text in ['_command_for("syft", root)', '_run_source_tool("syft", root', '"cyclonedx-json"', '"spdx-json"',
                 '"syft-json"', '"package-lock.json"', '"var/lib/dpkg/status"', 'result["findings"] == []']:
        assert text in source
    assert '"full_image_security_passed": False' in source
