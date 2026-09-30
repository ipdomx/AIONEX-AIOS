"""Pinned Grype source/build and fixture contracts; no production/network calls."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "web-dashboard/backend/scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("grype_build_contract", SCRIPTS / "build_grype.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.pop(0)


@pytest.fixture
def locked(tmp_path):
    value = json.loads((ROOT / "web-dashboard/backend/security-build/grype/lock.json").read_text())
    for name in ("go.mod", "go.sum"):
        p = tmp_path / name
        p.write_text("synthetic locked module file\n")
        value["files"][name] = m.sha(p)
    (tmp_path / "lock.json").write_text(json.dumps(value))
    return tmp_path, value


def test_exact_source_lock_accepted(locked):
    folder, value = locked
    assert m.read_lock(folder) == value
    real = m.read_lock(ROOT / "web-dashboard/backend/security-build/grype")
    assert real["toolchain_version"] == "go1.27.1"
    assert real["modules"]["github.com/docker/docker"] == "v28.5.2+incompatible"


@pytest.mark.parametrize("field", ["upstream_version", "local_version", "upstream_commit", "source_url", "source_sha256",
    "toolchain_version", "toolchain_url", "toolchain_sha256", "files", "modules", "build_date", "expected_binary_sha256"])
def test_missing_lock_field_denied(locked, field):
    folder, value = locked
    del value[field]
    (folder / "lock.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.read_lock(folder)


@pytest.mark.parametrize("field,value", [("upstream_version", "0.116.1"), ("local_version", "0.119.0"),
    ("upstream_commit", "main"), ("upstream_commit", None), ("source_url", "https://example.invalid/source"),
    ("source_sha256", "0" * 63), ("toolchain_version", "go1.27rc1"), ("toolchain_url", "http://go.dev/toolchain"),
    ("toolchain_sha256", "A" * 64), ("expected_binary_sha256", None), ("build_date", "today")])
def test_floating_or_malformed_identity_denied(locked, field, value):
    folder, lock = locked
    lock[field] = value
    (folder / "lock.json").write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        m.read_lock(folder)


@pytest.mark.parametrize("filename", ["go.mod", "go.sum"])
@pytest.mark.parametrize("fault", ["content", "symlink"])
def test_module_file_change_denied(locked, filename, fault):
    folder, _ = locked
    p = folder / filename
    if fault == "content":
        p.write_text("changed")
    else:
        other = folder / "other"
        p.rename(other)
        p.symlink_to(other)
    with pytest.raises(ValueError):
        m.read_lock(folder)


@pytest.mark.parametrize("fault", ["missing", "extra", "version"])
def test_linked_module_inventory_required(locked, fault):
    folder, value = locked
    if fault == "missing":
        del value["modules"]["github.com/docker/docker"]
    elif fault == "extra":
        value["modules"]["unexpected"] = "v1.0.0"
    else:
        value["modules"]["golang.org/x/crypto"] = "latest"
    (folder / "lock.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.read_lock(folder)


def test_symlink_lock_denied(locked):
    folder, _ = locked
    p = folder / "lock.json"
    other = folder / "actual"
    p.rename(other)
    p.symlink_to(other)
    with pytest.raises(ValueError):
        m.read_lock(folder)


def test_compiler_checksum_and_git_environment_are_pinned(monkeypatch):
    monkeypatch.setenv("GOSUMDB", "off")
    monkeypatch.setenv("GOTOOLCHAIN", "auto")
    monkeypatch.setenv("GOPRIVATE", "*")
    env = m.build_environment(Path("/owned/go"))
    assert env["GOSUMDB"] == "sum.golang.org" and env["GOTOOLCHAIN"] == "local"
    assert env["GOFLAGS"] == "-mod=readonly" and env["CGO_ENABLED"] == "0"
    assert env["GOPRIVATE"] == env["GONOSUMDB"] == env["GONOPROXY"] == ""
    assert env["GIT_CONFIG_GLOBAL"] == env["GIT_CONFIG_SYSTEM"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_local_version_and_reproducible_build_flags(locked):
    _, lock = locked
    args = m.build_command("go", Path("/owned/grype"), lock)
    assert "-trimpath" in args and "-buildvcs=false" in args
    flags = args[args.index("-ldflags") + 1]
    assert "main.version=0.119.0+aios.1" in flags and lock["upstream_commit"] in flags
    assert lock["build_date"] in flags and args[-1] == "./cmd/grype"


def test_source_and_tests_fingerprinted_not_private_git(tmp_path):
    (tmp_path / "source.go").write_text("package fixture\n")
    (tmp_path / "source_test.go").write_text("package fixture\n")
    a = m.fingerprint(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/master\n")
    assert m.fingerprint(tmp_path) == a
    (tmp_path / "source_test.go").write_text("changed test\n")
    assert m.fingerprint(tmp_path) != a


def fixture_db(root: Path, name: str, ids: list[str]) -> Path:
    d = root / "grype/matcher/python/testdata/cache/db/python-name-and-vex/selected" / name / "v6"
    d.mkdir(parents=True)
    with sqlite3.connect(d / "vulnerability.db") as conn:
        conn.execute("CREATE TABLE vulnerability_handles (name TEXT)")
        conn.executemany("INSERT INTO vulnerability_handles VALUES (?)", [(x,) for x in ids])
    (d / "import.json").write_text('{"digest":"synthetic-fixture"}')
    return d


def test_retained_fixture_is_exact_database_not_runtime_feed(tmp_path):
    source = tmp_path / "source"
    d = fixture_db(source, "one", [m.FIXTURE_ID])
    out = tmp_path / "out"
    proof = m.retain_test_fixture(source, out)
    assert proof["vulnerability_ids"] == [m.FIXTURE_ID]
    assert proof["upstream_test_fixture_not_production_feed"] and proof["not_installed_as_runtime_database"]
    for n, h in proof["database_files"].items():
        assert m.sha(d / n) == h == m.sha(out / "test-fixture-db/6" / n)


@pytest.mark.parametrize("fault", ["absent", "wrong-vulnerability", "duplicate", "missing-metadata", "symlink-db"])
def test_invalid_or_ambiguous_fixture_is_not_adopted(tmp_path, fault):
    source = tmp_path / "source"
    if fault != "absent":
        d = fixture_db(source, "one", ["other"] if fault == "wrong-vulnerability" else [m.FIXTURE_ID])
        if fault == "duplicate":
            fixture_db(source, "two", [m.FIXTURE_ID])
        elif fault == "missing-metadata":
            (d / "import.json").unlink()
        elif fault == "symlink-db":
            db = d / "vulnerability.db"
            db.rename(d / "real.db")
            db.symlink_to(d / "real.db")
    with pytest.raises(ValueError):
        m.retain_test_fixture(source, tmp_path / "out")


def test_selected_scope_includes_real_database_and_matchers():
    assert len(m.TEST_PACKAGES) == 8
    assert {"./grype/db/v6", "./grype/matcher/python", "./grype/matcher/javascript", "./grype/matcher/dpkg"} <= set(m.TEST_PACKAGES)
    text = (SCRIPTS / "build_grype.py").read_text()
    assert '"all_upstream_tests_claimed": False' in text
    assert '"--template="' in text and "docker.sock" not in text


def test_docker_runtime_never_installs_fixture_database_or_older_binary():
    text = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text()
    install = (SCRIPTS / "install-security-tools.sh").read_text()
    assert "AS grype-builder" in text
    assert "--from=grype-builder /build/grype-output/grype /usr/local/bin/grype" in text
    assert "grype-build-provenance.json" in text and "GRYPE-LICENSE" in text
    assert "test-fixture-db" not in text
    assert "install_tgz_release anchore/grype" not in install
    assert '"${GRYPE_VERSION}+aios.1"' in install and "GRYPE_VERSION=0.119.0" in install


def test_native_verifier_retains_checksum_gate_and_real_application_path():
    s = (SCRIPTS / "verify_security_grype.py").read_text()
    for value in ['_command_for("grype", root)', '_run_source_tool("grype", root',
                  '_normalize_source_findings("grype", payload', 'GRYPE_DB_VALIDATE_AGE="true"',
                  'GRYPE_DB_VALIDATE_BY_HASH_ON_START="true"', '"full_image_security_passed": False']:
        assert value in s
    assert '"--fixture-db"' in s and '"upstream_test_database_not_current_feed": True' in s
