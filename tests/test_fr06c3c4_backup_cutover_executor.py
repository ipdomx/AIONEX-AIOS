from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-06C3C4-backup-cutover-executor.json"
SCRIPT = ROOT / "scripts/security/fr06c3_backup_cutover.py"


def _c() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_executor_scope_is_backup_only() -> None:
    e = _c()["executor"]
    assert e["protected_services"] == ["backup-worker", "backend"]
    assert e["handles_key_material"] is False
    assert e["creates_or_unlocks_vault"] is False
    assert e["opens_admission"] is False
    assert e["changes_cloudflare"] is False
    assert _c()["scope_boundary"]["redis_touched"] is False
    assert _c()["scope_boundary"]["logs_moved"] is False


def test_cutover_is_offline_and_retains_legacy() -> None:
    c = _c()["cutover"]
    assert c["stop_order"] == ["backup-worker", "backend"]
    assert c["legacy_source_sealed_read_only_before_copy"] is True
    assert "offline exact rsync" in c["copy"]
    assert c["candidate_mount_acceptance"] is True
    assert c["legacy_deleted"] is False
    assert c["success_status"] == "candidate_backup_started_admission_closed"


def test_rollback_never_copies_while_candidate_writer_runs() -> None:
    r = _c()["rollback"]
    assert r["automatic_on_cutover_failure"] is True
    assert "stop candidate services" in r["post_candidate_start"]
    assert "reverse exact" in r["post_candidate_start"]
    assert r["blind_live_reverse_copy_allowed"] is False
    assert r["candidate_retained"] is True


def test_source_has_exact_confirmation_and_no_redis_mutation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "FR06C3_PRODUCTION_BACKUP_CUTOVER" in text
    assert "FR06C3_PRODUCTION_BACKUP_ROLLBACK" in text
    assert 'SERVICES = ("backup-worker", "backend")' in text
    assert "FLUSHALL" not in text
    assert "redis-cli" not in text
    assert '"rsync"' in text
    assert '"legacy_deleted": False' in text
    assert '"admission_opened": False' in text


def test_closeout_requires_backup_and_restore_from_candidate() -> None:
    gates = _c()["post_cutover_required_before_c3d_close"]
    assert any("encrypted R2" in item for item in gates)
    assert any("restore validation" in item for item in gates)
    assert any("read-only" in item for item in gates)
