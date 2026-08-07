from __future__ import annotations

from pathlib import Path

from aios.phase31e_acceptance import build_phase31e_report


ROOT = Path(__file__).resolve().parents[1]


def test_phase31e_full_end_to_end_acceptance(tmp_path: Path) -> None:
    report = build_phase31e_report(ROOT, tmp_path)
    assert report.passed is True
    assert len(report.cases) >= 2
    assert all(case.passed for case in report.cases)
    assert len(report.aggregate_sha256) == 64
    assert any(case.project_type == "3d_web_project" for case in report.cases)
    assert any(case.case_id == "repository-capability-chain" for case in report.cases)


def test_phase31e_report_is_deterministic(tmp_path: Path) -> None:
    first = build_phase31e_report(ROOT, tmp_path)
    second = build_phase31e_report(ROOT, tmp_path)
    assert first.aggregate_sha256 == second.aggregate_sha256
    assert first.to_json() == second.to_json()
