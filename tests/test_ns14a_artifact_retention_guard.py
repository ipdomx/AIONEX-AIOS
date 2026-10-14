"""Require retained original NS14A browser failure artifacts *before* runner removal."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "scripts/release/ns14a_validate_playwright_artifacts.py"
SPEC = importlib.util.spec_from_file_location("aios_ns14a_artifact_retention", MOD)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def report(fail=False):
    status = "unexpected" if fail else "expected"
    return {"suites": [{"specs": [
        {"title": f"NS14A original case {i}", "tests": [{
            "status": (status if i == 0 else "expected"),
            "results": [{
                "status": ("failed" if fail and i == 0 else "passed"),
                "attachments": (
                    [
                        {"name":"screenshot","path":"/test-results/case/test-failed-1.png"},
                        {"name":"trace","path":"/test-results/case/trace.zip"},
                        {"name":"error-context","path":"/test-results/case/error-context.md"},
                    ] if fail and i == 0 else []
                )
            }],
        }]}
        for i in range(6)
    ]}], "errors": []}


def write_artifacts(tmp_path):
    for relative in (
        "test-results/case/test-failed-1.png",
        "test-results/case/trace.zip",
        "test-results/case/error-context.md"
    ):
        p = tmp_path / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"synthetic-test-evidence")
    return tmp_path


def test_all_six_original_tests_pass_without_attachments(tmp_path):
    result = guard.audit(report(), tmp_path)
    assert result["cases_reported"] == 6
    assert result["retention_gate_passed"] is True
    assert result["all_original_tests_passed"] is True


def test_failed_case_with_all_artifacts_retained_does_not_become_release_success(tmp_path):
    result = guard.audit(report(True), write_artifacts(tmp_path))
    assert result["attachments_retained"] == 3
    assert result["retention_gate_passed"] is True
    assert result["all_original_tests_passed"] is False
    assert result["failed_result_nodes"] == 1


def test_missing_evidence_fails_closed(tmp_path):
    result = guard.audit(report(True), tmp_path)
    assert result["retention_gate_passed"] is False
    assert result["attachments_missing"] == 3


def test_empty_report_or_fewer_than_six_cases_is_rejected(tmp_path):
    assert not guard.audit({}, tmp_path)["retention_gate_passed"]
    partial = report()
    partial["suites"][0]["specs"].pop()
    assert not guard.audit(partial, tmp_path)["retention_gate_passed"]


def test_symlink_outside_private_evidence_dir_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside-evidence.png"
    outside.write_bytes(b"outside")
    target = tmp_path / "test-results/case/test-failed-1.png"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)
    for name in ("trace.zip","error-context.md"):
        (target.parent / name).write_bytes(b"valid")
    result = guard.audit(report(True), tmp_path)
    assert result["retention_gate_passed"] is False
    assert result["attachments_missing"] >= 1


def test_symlinked_directory_is_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    for name in ("test-failed-1.png","trace.zip","error-context.md"):
        (real / name).write_bytes(b"valid")
    child = tmp_path / "test-results"
    child.mkdir()
    (child / "case").symlink_to(real)
    assert not guard.audit(report(True), tmp_path)["retention_gate_passed"]


def test_parent_traversal_is_rejected(tmp_path):
    d = report(True)
    d["suites"][0]["specs"][0]["tests"][0]["results"][0]["attachments"][0]["path"] = "/test-results/../etc/shadow"
    result = guard.audit(d, write_artifacts(tmp_path))
    assert result["retention_gate_passed"] is False
    assert result["unsafe_paths"]


def test_zero_byte_evidence_is_not_accepted(tmp_path):
    write_artifacts(tmp_path)
    (tmp_path / "test-results/case/error-context.md").write_bytes(b"")
    assert not guard.audit(report(True), tmp_path)["retention_gate_passed"]


def test_unexpected_top_level_errors_cannot_be_ignored(tmp_path):
    d = report()
    d["errors"] = [{"message":"Playwright infrastructure interrupted"}]
    assert not guard.audit(d, tmp_path)["retention_gate_passed"]


def test_original_rejected_live_result_correctly_fails_retention_gate():
    path = Path(
        "/var/lib/aionex-migration/r1-management-20261008/"
        "FR07-NS14A-PR925-LIVE-ACCEPTANCE-20261014T0741Z/"
    )
    if not path.is_dir():
        pytest.skip("private original AIOS evidence unavailable")
    original = json.loads((path / "PLAYWRIGHT-RESULTS.json").read_text())
    result = guard.audit(original, path)
    assert result["cases_reported"] == 6
    assert result["failed_result_nodes"] >= 3
    assert result["attachments_missing"] >= 9
    assert result["retention_gate_passed"] is False



def test_runner_cleanup_is_structurally_after_evidence_validation():
    shell = (ROOT / "scripts/release/ns14a_collect_playwright_container_artifacts.sh").read_text()
    guard_call = shell.index('ns14a_validate_playwright_artifacts.py')
    deletion = shell.index('docker rm "$runner"')
    assert guard_call < deletion
    assert 'docker cp "$runner:/test-results/."' in shell
    assert 'aionex.acceptance.scope' in shell
    assert 'test "$(hostname)" = "nc-ph-4354"' in shell
    assert 'umask 077' in shell
    assert "--expected-tests 6" in shell


def test_root_only_release_retention_never_claims_browser_success_from_artifact_copy():
    shell = (ROOT / "scripts/release/ns14a_collect_playwright_container_artifacts.sh").read_text()
    assert "PLAYWRIGHT_EVIDENCE_RETAINED_BEFORE_RUNNER_REMOVAL" in shell
    assert "ALL_SIX_TESTS_PASSED" not in shell
    assert "RELEASE_ACCEPTED" not in shell
