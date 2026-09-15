from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-06C3C3-cutover-lifecycle-contract.json"


def _c() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_backup_cutover_requires_offline_exact_copy_and_restore_proof() -> None:
    b = _c()["local_backup_cutover"]
    assert b["protected_services"] == ["backend", "backup-worker"]
    assert b["source_must_be_sealed_read_only_before_final_copy"] is True
    assert b["copy_mode"] == "offline_exact_manifest_copy"
    assert b["live_copy_while_backup_worker_can_write"] is False
    assert "new encrypted R2 backup from candidate completes" in b["post_cutover_acceptance"]
    assert b["legacy_source_deleted"] is False


def test_redis_client_matrix_is_explicit_and_includes_realtime() -> None:
    r = _c()["redis_cutover"]
    clients = r["database_clients"]
    assert len(clients) == r["database_client_definition_count"] == 26
    assert len(clients) == len(set(clients))
    assert "backend" in clients
    assert "project-worker" in clients
    assert "realtime-egress" in clients
    assert "realtime-livekit" in clients
    assert "backup-worker" in clients


def test_redis_cutover_never_copies_aof_and_starts_empty() -> None:
    r = _c()["redis_cutover"]
    assert r["legacy_aof_copy_allowed"] is False
    assert r["candidate_initial_state"] == "empty"
    assert r["restart_policy"] == "no"
    assert "require candidate DBSIZE=0 before clients" in r["cutover_order"]
    assert "never reverse-copy volatile candidate AOF" in r["rollback_policy"]


def test_contract_has_no_production_execution_authority() -> None:
    s = _c()["safety"]
    assert s["production_execution_by_this_contract"] is False
    assert s["application_admission_opened"] is False
    assert s["cloudflare_changed"] is False
    assert s["backup_legacy_deleted"] is False
    assert s["redis_legacy_deleted"] is False
    assert s["redis_promoted_to_dr_authority"] is False
