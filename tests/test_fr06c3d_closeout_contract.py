from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs/project/receipts/FR-06C3D-local-backup-cutover-closeout.json"


def _r() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_cutover_and_recovery_are_accepted_but_fr06_stays_open() -> None:
    r = _r()
    assert r["subpart"] == "FR-06C3D"
    assert r["production_cutover"]["status"] == "candidate_backup_started_admission_closed"
    assert r["post_cutover_recovery"]["backup_status"] == "completed"
    assert r["post_cutover_recovery"]["offsite_status"] == "completed"
    assert r["post_cutover_recovery"]["restore_validated"] is True
    assert r["post_cutover_recovery"]["restore_offsite_validated"] is True
    assert r["release_boundary"]["fr06_completed"] is False


def test_owner_fix_matches_runtime_user_and_preserves_rollback() -> None:
    r = _r()
    assert r["runtime_correction"]["correct_owner"] == "1000:1000"
    assert r["runtime_correction"]["mode"] == "0700"
    assert r["runtime_acceptance"]["backup_worker_healthy"] is True
    assert r["rollback"]["legacy_backup_data_retained"] is True
    assert r["rollback"]["legacy_backup_data_read_only"] is True
    assert r["rollback"]["blind_live_reverse_copy_allowed"] is False


def test_c3d_did_not_touch_redis_logs_or_release_admission() -> None:
    r = _r()["release_boundary"]
    assert r["next_subpart"] == "FR-06C3E"
    assert r["redis_touched_by_c3d"] is False
    assert r["host_logs_touched_by_c3d"] is False
    assert r["admission_opened_by_encryption_batch"] is False
    assert r["cloudflare_changed"] is False
