from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / "docs" / "project" / "receipts"
PLAN = ROOT / "docs" / "project" / "PLAN.json"


def test_fr04c5_all_fr04c_receipts_are_present() -> None:
    required = [
        "FR-04C1-hardlink-policy.md",
        "FR-04C2-cache-socket-model-redis-policy.md",
        "FR-04C3-redis-recovery-contract.md",
        "FR-04C3-redis-recovery-contract.json",
        "FR-04C4-db-assets-retention-contract.md",
        "FR-04C5-parent-closure.md",
    ]
    for name in required:
        assert (RECEIPTS / name).is_file(), name


def test_fr04c5_parent_closure_does_not_start_fr04d() -> None:
    closure = (RECEIPTS / "FR-04C5-parent-closure.md").read_text(encoding="utf-8")
    assert "No runtime code, Compose service, image, or backup-worker behavior changes" in closure
    assert "FR-04D can start only after this parent closure PR is merged and recorded" in closure
    plan = PLAN.read_text(encoding="utf-8")
    assert "FR-04D اختبار نسخة غير فارغة" in plan
    assert "FR-04C ضبط اتساق DB والأصول" in plan


def test_fr04c5_plan_keeps_fr04d_after_fr04c() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    assert "FR-04C ضبط اتساق DB والأصول والاحتفاظ ومنع مسارات وروابط غير آمنة" in plan
    assert "FR-04D اختبار نسخة غير فارغة ومقارنة البصمات ثم نشر وقبول التغطية" in plan
