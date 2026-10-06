"""Build-contract and real ZIP/RECORD tests; never execute scanner targets."""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "web-dashboard/backend/scripts/build_semgrep_compat_wheel.py"
spec = importlib.util.spec_from_file_location("semgrep_compat_wheel", SCRIPT)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def wheel(tmp_path, *, metadata=None, extra=None, bad_record=False, duplicate=False, symlink=False):
    metadata = metadata if metadata is not None else (
        "Metadata-Version: 2.1\nName: semgrep\nVersion: 1.178.0\n"
        "Requires-Dist: mcp==1.29.0\n" + m.OLD_REQUIREMENT + "\nFixture description.\n"
    )
    payload = {
        "semgrep/__init__.py": b"version = '1.178.0'\n",
        "semgrep/bin/semgrep-core": b"synthetic executable payload, never executed\n",
        m.OLD_DIST + "METADATA": metadata.encode(),
        m.OLD_DIST + "WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
        m.OLD_DIST + "licenses/LICENSE": b"synthetic license retained\n",
        **(extra or {}),
    }
    rows = [(n, m.record_hash(v), str(len(v))) for n, v in payload.items()]
    if bad_record:
        rows[0] = (rows[0][0], "sha256=" + "0" * 43, rows[0][2])
    rows.append((m.OLD_DIST + "RECORD", "", ""))
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    payload[m.OLD_DIST + "RECORD"] = buffer.getvalue().encode()
    source = tmp_path / m.UPSTREAM_NAME
    with zipfile.ZipFile(source, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in payload.items():
            item = zipfile.ZipInfo(name, (2026, 9, 23, 0, 0, 0))
            item.external_attr = (stat.S_IFREG | 0o755) << 16
            if symlink and name == "semgrep/__init__.py":
                item.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(item, data)
        if duplicate:
            with pytest.warns(UserWarning, match="Duplicate"):
                z.writestr("semgrep/__init__.py", b"extra")
    return source, payload


def build(tmp_path, source):
    return m.rewrite_wheel(source, tmp_path / "out", expected_sha256=m.digest(source.read_bytes()))


def test_derived_identity_exact_delta_and_payload_bytes(tmp_path):
    source, original = wheel(tmp_path)
    result = build(tmp_path, source)
    target = tmp_path / "out" / result["derived_wheel"]
    assert result["local_version"] == "1.178.0+aios.2"
    assert result["only_metadata_changed"] and not result["dependency_checks_disabled"]
    assert result["derived_sha256"] == m.digest(target.read_bytes())
    with zipfile.ZipFile(target) as z:
        assert all(not n.startswith(m.OLD_DIST) for n in z.namelist())
        for name, data in original.items():
            if name.endswith(("/METADATA", "/RECORD")):
                continue
            new_name = name.replace(m.OLD_DIST, m.NEW_DIST)
            assert z.read(new_name) == data
        meta = z.read(m.NEW_DIST + "METADATA").decode()
        assert m.NEW_REQUIREMENT in meta and m.OLD_REQUIREMENT not in meta
        assert "Requires-Dist: mcp==1.29.0\n" in meta
        assert "Version: 1.178.0+aios.2\n" in meta
        for name, hashed, size in csv.reader(io.StringIO(z.read(m.NEW_DIST + "RECORD").decode())):
            if name.endswith("/RECORD"):
                assert hashed == size == ""
            else:
                data = z.read(name)
                assert (hashed, size) == (m.record_hash(data), str(len(data)))
    proof = json.loads((target.parent / "semgrep-compat-provenance.json").read_text())
    assert proof == result


def test_deterministic_rebuild_into_distinct_empty_output(tmp_path):
    source, _ = wheel(tmp_path)
    a = build(tmp_path, source)
    b = m.rewrite_wheel(source, tmp_path / "second", expected_sha256=m.digest(source.read_bytes()))
    assert a == b


def test_existing_output_not_overwritten(tmp_path):
    source, _ = wheel(tmp_path)
    first = build(tmp_path, source)
    with pytest.raises(FileExistsError):
        build(tmp_path, source)
    assert json.loads((tmp_path / "out/semgrep-compat-provenance.json").read_text()) == first


@pytest.mark.parametrize("digest", ["0" * 64, "invalid", "F" * 64])
def test_hash_mismatch_precedes_output_creation(tmp_path, digest):
    source, _ = wheel(tmp_path)
    with pytest.raises(ValueError):
        m.rewrite_wheel(source, tmp_path / "out", expected_sha256=digest)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("mutation", ["name", "version", "old_pin", "duplicate_pin", "mcp"])
def test_upstream_metadata_drift_rejected_not_silently_rewritten(tmp_path, mutation):
    meta = "Name: semgrep\nVersion: 1.178.0\nRequires-Dist: mcp==1.29.0\n" + m.OLD_REQUIREMENT
    edits = {
        "name": ("Name: semgrep", "Name: other"),
        "version": ("Version: 1.178.0", "Version: 1.178.1"),
        "old_pin": (m.OLD_REQUIREMENT, "Requires-Dist: pyjwt>=2\n"),
        "duplicate_pin": (m.OLD_REQUIREMENT, m.OLD_REQUIREMENT * 2),
        "mcp": ("mcp==1.29.0", "mcp==1.23.3"),
    }
    source, _ = wheel(tmp_path, metadata=meta.replace(*edits[mutation]))
    with pytest.raises(ValueError, match="metadata changed"):
        build(tmp_path, source)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("bad_name", ["../escape", "/absolute", "some/../escape", "back\\slash", m.OLD_DIST + "RECORD.jws"])
def test_unsafe_or_signed_archive_never_unpacked(tmp_path, bad_name):
    source, _ = wheel(tmp_path, extra={bad_name: b"preserve input only"})
    with pytest.raises(ValueError):
        build(tmp_path, source)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("fault", ["bad_record", "duplicate", "symlink"])
def test_member_integrity_required_before_repack(tmp_path, fault):
    source, _ = wheel(tmp_path, **{fault: True})
    with pytest.raises(ValueError):
        build(tmp_path, source)
    assert not (tmp_path / "out").exists()


def test_input_symlink_and_size_limit_rejected(tmp_path, monkeypatch):
    source, _ = wheel(tmp_path)
    link = tmp_path / "alias.whl"
    link.symlink_to(source)
    with pytest.raises(ValueError):
        build(tmp_path, link)
    monkeypatch.setattr(m, "MAX_ARCHIVE", 1)
    with pytest.raises(ValueError):
        build(tmp_path, source)


def test_application_and_semgrep_resolve_in_separate_environments():
    base = ROOT / "web-dashboard/backend"
    dockerfile = (base / "Dockerfile.security-tools").read_text()
    assert "AS semgrep-builder" in dockerfile
    assert "-r requirements-runtime.txt -r requirements-security-tools.txt" in dockerfile
    assert "/opt/venv/bin/python -m pip check" in dockerfile
    assert "/opt/semgrep/bin/python -m pip check" in dockerfile
    assert "COPY --from=semgrep-builder /opt/semgrep /opt/semgrep" in dockerfile
    assert "ln -s /opt/semgrep/bin/semgrep /usr/local/bin/semgrep" in dockerfile
    tool_pins = (base / "requirements-security-tools.txt").read_text()
    assert "semgrep==" not in tool_pins and "opentelemetry-api==1.44.0" in tool_pins
    isolated = (base / "requirements-security-semgrep.txt").read_text()
    for pin in ("semgrep==1.178.0+aios.2", "mcp==1.29.0", "PyJWT[crypto]==2.15.0"):
        assert pin in isolated


def test_cleanup_removes_obsolete_system_code_not_a_scan_ignore():
    source = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text()
    for path in ("site-packages/pip*", "site-packages/setuptools*", "site-packages/pkg_resources", "site-packages/wheel*"):
        assert path in source
    assert "--ignore-unfixed" not in source and "--ignore-vuln" not in source
    assert "COPY --from=builder /opt/venv /opt/venv" in source
    assert "USER 1000:1000" in source
