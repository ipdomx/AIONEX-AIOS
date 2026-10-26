"""Strict source-custody tests; no production scripts, services or network."""
from __future__ import annotations

import hashlib
import importlib.util
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/operations/ns12_dns_diagnostic_source_guard.py"
SPEC = importlib.util.spec_from_file_location("ns12_guard_test", SCRIPT)
assert SPEC and SPEC.loader
ns12 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ns12)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture():
    original = b"NS12-not-production\n" + ns12.DEFECT + b"\n# original unchanged\n"
    fixed = original.replace(ns12.DEFECT, ns12.REPAIR)
    return original, fixed


def test_one_line_pinned_change_only():
    original, expected = fixture()
    output = ns12.guarded_patch(
        original, original_sha256=hash_bytes(original),
        prepared_sha256=hash_bytes(expected)
    )
    assert output == expected
    assert original != output
    assert output.count(ns12.REPAIR) == 1
    assert output.count(ns12.DEFECT) == 0


@pytest.mark.parametrize("changed", [
    b"other", b"", b"NS12-malformed\n" + ns12.DEFECT,
])
def test_dirty_or_missing_source_refused(changed):
    original, fixed = fixture()
    with pytest.raises(ValueError, match="SHA"):
        ns12.guarded_patch(changed, original_sha256=hash_bytes(original),
                           prepared_sha256=hash_bytes(fixed))


def test_multiple_patch_targets_cannot_be_guessed():
    original, fixed = fixture()
    doubled = original + ns12.DEFECT
    with pytest.raises(ValueError, match="not unique"):
        ns12.guarded_patch(doubled, original_sha256=hash_bytes(doubled),
                           prepared_sha256=hash_bytes(fixed))


def test_wrong_output_sha_fails_closed():
    original, _ = fixture()
    with pytest.raises(ValueError, match="corrected"):
        ns12.guarded_patch(
            original, original_sha256=hash_bytes(original),
            prepared_sha256="0" * 64
        )


def test_create_only_and_idempotent_staging(tmp_path):
    original, fixed = fixture()
    source = tmp_path / "source_v9.py"
    target = tmp_path / "source_v10.py"
    source.write_bytes(original)
    kwargs={"original_sha256":hash_bytes(original),
            "prepared_sha256":hash_bytes(fixed)}
    assert ns12.prepare(source, target, **kwargs) == "CREATED_EXACT_UNACTIVATED"
    assert target.read_bytes() == fixed
    assert source.read_bytes() == original
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert ns12.prepare(source, target, **kwargs) == "ALREADY_PREPARED_EXACT"


def test_dirty_existing_staged_file_will_never_be_overwritten(tmp_path):
    original, fixed = fixture()
    source = tmp_path / "original.py"
    target = tmp_path / "next.py"
    source.write_bytes(original)
    target.write_bytes(b"do not replace me")
    before=target.read_bytes()
    with pytest.raises(ValueError, match="differs"):
        ns12.prepare(source,target,
                     original_sha256=hash_bytes(original),
                     prepared_sha256=hash_bytes(fixed))
    assert target.read_bytes()==before


def test_unsafe_stage_permissions_are_rejected(tmp_path):
    original, fixed = fixture()
    source=tmp_path/"original.py"
    target=tmp_path/"next.py"
    source.write_bytes(original)
    target.write_bytes(fixed)
    target.chmod(0o644)
    with pytest.raises(ValueError, match="differs"):
        ns12.prepare(source,target,
                     original_sha256=hash_bytes(original),
                     prepared_sha256=hash_bytes(fixed))


def test_symlink_original_or_target_is_rejected(tmp_path):
    original, fixed = fixture()
    source=tmp_path/"source.py"
    target=tmp_path/"target.py"
    alt=tmp_path/"outside.py"
    alt.write_bytes(original)
    source.symlink_to(alt)
    with pytest.raises(ValueError, match="symlinks"):
        ns12.prepare(source,target,
                     original_sha256=hash_bytes(original),
                     prepared_sha256=hash_bytes(fixed))
    source.unlink()
    source.write_bytes(original)
    target.symlink_to(alt)
    with pytest.raises(ValueError, match="symlinks"):
        ns12.prepare(source,target,
                     original_sha256=hash_bytes(original),
                     prepared_sha256=hash_bytes(fixed))


def test_canonical_paths_and_no_service_controller_imports():
    assert ns12.ORIGINAL.name == "ns12_observer_v9_g7.py"
    assert ns12.PREPARED.name == "ns12_observer_v10_g7_diagnostic_only.py"
    data=SCRIPT.read_text(encoding="utf-8")
    assert "systemctl" not in data
    assert "subprocess.run" not in data
    assert "docker exec" not in data
    assert "requests." not in data
