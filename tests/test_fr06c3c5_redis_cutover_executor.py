from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-06C3C5-redis-cutover-executor.json"
SCRIPT = ROOT / "scripts/security/fr06c3_redis_cutover.py"
LIFECYCLE = ROOT / "docs/project/receipts/FR-06C3C3-cutover-lifecycle-contract.json"


def _j(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_executor_has_no_aof_copy_or_post_client_blind_rollback() -> None:
    e = _j(CONTRACT)["executor"]
    assert e["legacy_aof_copy_capability"] is False
    assert e["post_client_blind_rollback_capability"] is False
    assert e["opens_admission"] is False
    assert e["changes_cloudflare"] is False
    assert e["commands"] == ["inspect-runtime", "plan-cutover", "apply-cutover"]


def test_preflight_requires_realtime_and_durable_drain() -> None:
    p = _j(CONTRACT)["preflight"]
    for key in ("active_backup_jobs", "active_restore_validations", "active_durable_external_jobs", "active_realtime_sessions", "active_livekit_rooms"):
        assert p[key] == 0
    assert p["application_admission_closed"] is True
    assert p["fresh_encrypted_backup_restore_required"] is True
    assert p["c3d_local_backup_closeout_required"] is True


def test_client_matrix_matches_lifecycle_contract() -> None:
    c = _j(CONTRACT)["cutover"]
    lifecycle = _j(LIFECYCLE)["redis_cutover"]
    assert c["redis_client_definition_count"] == lifecycle["database_client_definition_count"] == 26
    assert c["candidate_must_start_with_dbsize"] == 0
    assert c["legacy_aof_copied"] is False
    assert c["restart_only_previously_running_clients"] is True


def test_failure_policy_is_fail_closed_after_client_start() -> None:
    f = _j(CONTRACT)["failure_policy"]
    assert "quiesced legacy Redis" in f["before_any_candidate_client_starts"]
    assert "fail closed" in f["after_any_candidate_client_starts"]
    assert "never resurrect" in f["after_any_candidate_client_starts"]
    assert f["candidate_to_legacy_aof_reverse_copy_allowed"] is False


def test_source_contains_no_rsync_or_redis_aof_copy_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"rsync"' not in text
    assert "FR06C3_PRODUCTION_REDIS_CUTOVER" in text
    assert '"legacy_aof_copied":False' in text.replace(" ", "")
    assert '"candidate_initial_dbsize":0' in text.replace(" ", "")
    assert "active_realtime_sessions" in text
    assert "active_livekit_rooms" in text
    assert "manual empty/reconciliation recovery is required" in text
