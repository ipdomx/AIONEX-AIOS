"""Pinned Gitleaks builder contracts; all archives and mutations are synthetic."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
P = BACKEND / "scripts/build_gitleaks.py"
spec = importlib.util.spec_from_file_location("gitleaks_builder", P)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def locked(tmp_path):
    target = tmp_path / "lock"
    shutil.copytree(BACKEND / "security-build/gitleaks", target)
    return target, json.loads((target / "lock.json").read_text())


def bundle(tmp_path, members):
    path = tmp_path / "fixture.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, kind, value in members:
            info = tarfile.TarInfo(name)
            info.mode = 0o755 if name.endswith("tool") else 0o644
            if kind == "file":
                data = value.encode()
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                info.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                             "directory": tarfile.DIRTYPE, "fifo": tarfile.FIFOTYPE}[kind]
                info.linkname = value
                tar.addfile(info)
    return path


def test_current_lock_is_complete_and_hash_pinned(tmp_path):
    path, expected = locked(tmp_path)
    assert m.read_lock(path) == expected
    assert expected["local_version"] == "8.30.1+aios.1"
    assert expected["toolchain_version"] == "go1.27.1"
    assert expected["modules"]["golang.org/x/crypto"] == "v0.55.0"
    assert expected["modules"]["golang.org/x/text"] == "v0.41.0"


@pytest.mark.parametrize("field,value", [
    ("upstream_commit", "master"), ("source_url", "http://untrusted.invalid/source"),
    ("toolchain_version", "go1.27rc1"), ("toolchain_url", "https://untrusted.invalid/go.tar.gz"),
    ("local_version", "8.30.1"), ("source_sha256", "0"),
    ("toolchain_sha256", "Z" * 64), ("expected_binary_sha256", "unlocked"),
    ("modules", {"golang.org/x/crypto": "v0.55.0"}), ("files", {"go.mod": "0" * 64}),
])
def test_lock_drift_denied_before_any_build(tmp_path, field, value):
    path, document = locked(tmp_path)
    document[field] = value
    (path / "lock.json").write_text(json.dumps(document))
    with pytest.raises(ValueError):
        m.read_lock(path)


@pytest.mark.parametrize("name", ["go.mod", "go.sum"])
def test_module_lock_bytes_cannot_drift(tmp_path, name):
    path, _ = locked(tmp_path)
    with (path / name).open("a") as stream:
        stream.write("\nchanged\n")
    with pytest.raises(ValueError, match="Module lock changed"):
        m.read_lock(path)


def test_module_lock_cannot_be_replaced_by_a_symlink(tmp_path):
    path, _ = locked(tmp_path)
    original = path / "go.mod"
    original.rename(path / "elsewhere")
    original.symlink_to("elsewhere")
    with pytest.raises(ValueError, match="Module lock changed"):
        m.read_lock(path)


def test_verified_archive_preserves_upstream_file_symlink_and_mode(tmp_path):
    archive = bundle(tmp_path, [("project/bin/tool", "file", "synthetic"),
                                ("project/fixture/link", "symlink", "../bin/tool")])
    result = m.extract_verified(archive, m.sha(archive), tmp_path / "out")
    assert result.name == "project" and (result / "bin/tool").read_text() == "synthetic"
    assert (result / "fixture/link").is_symlink()
    assert (result / "fixture/link").read_text() == "synthetic"
    assert (result / "bin/tool").stat().st_mode & 0o111


@pytest.mark.parametrize("members", [
    [("../escape", "file", "x")], [("/absolute", "file", "x")],
    [("project/a/../escape", "file", "x")], [("project/back\\slash", "file", "x")],
    [("project/file", "file", "a"), ("project/file", "file", "b")],
    [("one/file", "file", "a"), ("two/file", "file", "b")],
    [("project/link", "symlink", "/etc/passwd")],
    [("project/link", "symlink", "../../escape")],
    [("project/link", "hardlink", "project/file")],
    [("project/pipe", "fifo", "")], [],
])
def test_unsafe_archives_rejected_without_creating_destination(tmp_path, members):
    archive = bundle(tmp_path, members)
    destination = tmp_path / "out"
    with pytest.raises(ValueError):
        m.extract_verified(archive, m.sha(archive), destination)
    assert not destination.exists()


def test_hash_mismatch_does_not_extract(tmp_path):
    archive = bundle(tmp_path, [("project/file", "file", "x")])
    with pytest.raises(ValueError, match="Unverified"):
        m.extract_verified(archive, "0" * 64, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_existing_destination_never_overwritten(tmp_path):
    archive = bundle(tmp_path, [("project/file", "file", "x")])
    out = tmp_path / "out"
    out.mkdir()
    (out / "owned-by-other").write_text("preserve")
    with pytest.raises(ValueError, match="already exists"):
        m.extract_verified(archive, m.sha(archive), out)
    assert (out / "owned-by-other").read_text() == "preserve"


def test_source_fingerprint_covers_code_and_embedded_rules(tmp_path):
    for name in ["main.go", "LICENSE", "config/gitleaks.toml", "report_templates/default.tmpl"]:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("original")
    before = m.source_fingerprint(tmp_path)
    assert len(before) == 4
    (tmp_path / "config/gitleaks.toml").write_text("changed detection rule")
    assert m.source_fingerprint(tmp_path) != before


def test_source_build_is_pinned_without_resolver_or_checksum_bypass():
    source = P.read_text()
    assert '"GOTOOLCHAIN": "local"' in source and '"GOSUMDB": "sum.golang.org"' in source
    assert '"GOFLAGS": "-mod=readonly"' in source and '"mod", "verify"' in source
    assert '"-count=1", "-json", "./..."' in source and '"-trimpath"' in source
    assert 'if sha(binary) != lock["expected_binary_sha256"]' in source
    assert '"get"' not in source and 'GOSUMDB=off' not in source


def test_full_docker_build_installs_verified_binary_not_old_release():
    dockerfile = (BACKEND / "Dockerfile.security-tools").read_text()
    installer = (BACKEND / "scripts/install-security-tools.sh").read_text()
    assert "AS gitleaks-builder" in dockerfile
    assert "COPY --from=gitleaks-builder /build/gitleaks-output/gitleaks /usr/local/bin/gitleaks" in dockerfile
    assert "GITLEAKS_VERSION=8.30.1+aios.1" in installer
    assert "install_tgz_release gitleaks/gitleaks" not in installer
    assert '"$GITLEAKS_SHA256" /usr/local/bin/gitleaks | sha256sum -c -' in installer
    lock = m.read_lock(BACKEND / "security-build/gitleaks")
    assert lock["expected_binary_sha256"] in installer
    assert "GITLEAKS-LICENSE" in dockerfile and "gitleaks-build-provenance.json" in dockerfile


def test_build_lock_read_does_not_mutate_input(tmp_path):
    path, _ = locked(tmp_path)
    before = {p.name: p.read_bytes() for p in path.iterdir()}
    result = m.read_lock(path)
    changed = copy.deepcopy(result)
    changed["modules"]["golang.org/x/crypto"] = "v0.0.0"
    assert {p.name: p.read_bytes() for p in path.iterdir()} == before
