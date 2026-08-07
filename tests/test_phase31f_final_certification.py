from pathlib import Path

from aios.phase31f_certification import certify_repository

ROOT = Path(__file__).resolve().parents[1]


def test_phase31f_repository_certification_passes() -> None:
    report = certify_repository(ROOT)
    assert report.passed, [(item.path, item.code) for item in report.findings]
    assert report.findings == ()
    assert len(report.aggregate_sha256) == 64


def test_phase31f_no_stale_backup_artifacts_are_tracked() -> None:
    assert not any(path.suffix in {".bak", ".orig", ".rej"} for path in (ROOT / "src").rglob("*"))
