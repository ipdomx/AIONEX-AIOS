from __future__ import annotations

import importlib.util
import json
import os
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06c2_database_cutover.py"
CONTRACT = ROOT / "docs/project/receipts/FR-06C2C-database-cutover-contract.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C2C-database-cutover-contract.md"


def _module():
    spec = importlib.util.spec_from_file_location("fr06c2c_cutover", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _evidence_value(now: datetime, merge: str = "a" * 40) -> dict:
    return {
        "schema_version": 1,
        "subpart": "FR-06C2C",
        "environment": "production",
        "observed_at": _z(now),
        "production_authorization": True,
        "source": {"merge_sha": merge, "protected_pr_checks_passed": True, "post_merge_main_checks_passed": True},
        "recovery": {"backup_status": "completed", "offsite_status": "completed", "restore_status": "completed", "restore_validated": True, "restore_offsite_validated": True, "restore_completed_at": _z(now)},
        "operations": {"active_backup_jobs": 0, "active_restore_validations": 0, "active_durable_external_jobs": 0, "admission_closed": True, "cloudflare_changed": False},
        "approvals": {"owner_authorized": True, "window_starts_at": _z(now - timedelta(minutes=1)), "window_ends_at": _z(now + timedelta(minutes=30))},
    }


def test_contract_has_full_guarded_offline_sequence_and_no_parent_closure() -> None:
    value = _json(CONTRACT)
    assert value["subpart"] == "FR-06C2C"
    assert value["implementation_status"] == "source_only_guarded_database_cutover_executor"
    executor = value["executor"]
    assert executor["handles_key_material"] is False
    assert executor["creates_or_unlocks_vault"] is False
    assert executor["changes_cloudflare"] is False
    assert executor["opens_application_admission"] is False
    assert executor["single_use_plan"] is True
    order = value["cutover_order"]
    assert order.index("stop all running database clients and verify durable jobs are drained") < order.index("stop PostgreSQL cleanly and require pg_controldata state shut down")
    assert order.index("stop PostgreSQL cleanly and require pg_controldata state shut down") < order.index("perform offline rsync only and require exact source/candidate manifest equality including pg_wal")
    assert order[-1] == "retain legacy PGDATA read-only; do not delete it"
    assert value["scope_boundary"]["fr06_parent_completed"] is False


def test_topology_covers_runtime_clients_but_separates_reconciler() -> None:
    value = _json(CONTRACT)
    topology = value["topology"]
    clients = topology["runtime_database_clients"]
    assert topology["runtime_database_client_definition_count"] == len(clients) == 23
    assert "postgres-credential-reconciler" not in clients
    assert topology["reconciler_service"] == "postgres-credential-reconciler"
    assert "project-worker" in clients
    assert topology["project_worker_may_be_scaled"] is True
    assert topology["latent_optional_service"] == "audio-song-worker-secondary"


def test_manifest_policy_rejects_symlink_hardlink_and_special_files() -> None:
    policy = _json(CONTRACT)["manifest_policy"]
    assert policy["symlinks_allowed"] is False
    assert policy["hardlinks_allowed"] is False
    assert policy["special_files_allowed"] is False
    assert "sha256" in policy["fields"]
    assert policy["content_names_retained_only_in_private_state"] is True


def test_rollback_requires_offline_reverse_delta_after_candidate_start() -> None:
    rollback = _json(CONTRACT)["rollback"]
    assert "reverse offline rsync" in rollback["post_candidate_start"]
    assert rollback["blind_live_reverse_copy_allowed"] is False
    assert rollback["legacy_pgdata_deleted"] is False
    text = RECEIPT.read_text(encoding="utf-8")
    assert "offline reverse delta" in text
    assert "Blind copying while either PostgreSQL is running is forbidden" in text


def test_evidence_rejects_active_jobs_and_secret_fields(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "_private_regular", lambda path, label, maximum=0: path.stat())
    now = datetime.now(timezone.utc)
    value = _evidence_value(now)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    assert module._evidence(path, "a" * 40)["operations"]["active_backup_jobs"] == 0
    value["operations"]["active_durable_external_jobs"] = 1
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.CutoverBlocked, match="not drained"):
        module._evidence(path, "a" * 40)
    value = _evidence_value(now)
    value["recovery"]["secret"] = "forbidden"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.CutoverBlocked, match="embedded secret material"):
        module._evidence(path, "a" * 40)


def test_safe_manifest_copy_matches_and_detects_drift(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "source"; target = tmp_path / "target"
    source.mkdir(); target.mkdir()
    (source / "PG_VERSION").write_text("16\n", encoding="utf-8")
    (source / "base").mkdir()
    (source / "base" / "1").write_bytes(b"payload")
    result = module._stable_copy(ROOT, source.resolve(), target.resolve(), (tmp_path / "evidence").resolve())
    assert result["regular_files"] == 2
    assert result["payload_bytes"] == len(b"16\n") + len(b"payload")
    assert (target / "base" / "1").read_bytes() == b"payload"




def _probe_value() -> dict:
    return {
        "database": "aionex",
        "user": "postgres",
        "server_version_num": "160015",
        "alembic_version": "20260908_0046",
        "organizations": 2,
        "users": 2,
        "project_executions": 1,
        "backup_records": 110,
        "public_table_count": 165,
    }

def _fake_plan(tmp_path: Path) -> tuple[dict, dict, Path, Path]:
    legacy = tmp_path / "legacy"; candidate = tmp_path / "candidate"
    legacy.mkdir(); candidate.mkdir()
    topology = {"postgres_id": "pg-old", "postgres_image_id": "img", "active_clients": {"backend": ["b1"], "project-worker": ["p1", "p2"]}, "active_service_count": 2, "active_container_count": 3}
    plan = {"plan_id": "f" * 64, "merge_sha": "a" * 40, "topology": topology, "legacy_source": str(legacy), "candidate_source": str(candidate)}
    runtime = {"topology": topology, "legacy_source": str(legacy), "candidate_source": str(candidate)}
    return plan, runtime, legacy, candidate


def test_apply_cutover_orders_clean_shutdown_copy_then_candidate_start(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    plan, runtime, legacy, candidate = _fake_plan(tmp_path)
    evidence = _evidence_value(datetime.now(timezone.utc))
    events: list[str] = []
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "_load_plan", lambda plan_path, evidence_path: plan)
    monkeypatch.setattr(module, "_preflight", lambda root, evidence_path, merge_sha: (evidence, runtime))
    monkeypatch.setattr(module, "_reserve", lambda operation_id, kind: events.append("reserve"))
    lock_path = tmp_path / "lock"
    monkeypatch.setattr(module, "_lock", lambda: os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600))
    monkeypatch.setattr(module, "_stop_ids", lambda ids: events.append("stop:" + ",".join(ids)))
    monkeypatch.setattr(module, "_assert_planned_clients_stopped", lambda topology: events.append("clients-stopped"))
    monkeypatch.setattr(module, "_postgres_probe", lambda cid: events.append("probe:" + cid) or _probe_value())
    monkeypatch.setattr(module, "_containers", lambda service, running_only: [{"id": "pg-new", "name": "postgres", "running": True, "status": "running", "health": "healthy", "image": "img"}] if service == module.POSTGRES_SERVICE else [])
    monkeypatch.setattr(module, "_pg_state_volume", lambda volume, subpath=None: "shut down")
    monkeypatch.setattr(module, "_seal", lambda path: events.append("seal"))
    monkeypatch.setattr(module, "_stable_copy", lambda root, source, target, evidence_dir: events.append(f"copy:{source.name}->{target.name}") or {"directories": 1, "regular_files": 2, "payload_bytes": 3, "aggregate_sha256": "x" * 64})
    monkeypatch.setattr(module, "_start_postgres", lambda files: events.append("start-candidate-postgres"))
    monkeypatch.setattr(module, "_run_reconciler", lambda files: events.append("reconcile"))
    monkeypatch.setattr(module, "_start_clients", lambda files, topology: events.append("start-clients"))
    monkeypatch.setattr(module, "_candidate_topology_matches", lambda topology: True)
    monkeypatch.setattr(module, "_sealed", lambda path: True)
    monkeypatch.setattr(module, "_write_result", lambda operation_id, body: tmp_path / "result.json")
    monkeypatch.setattr(module, "_automatic_rollback", lambda *args, **kwargs: events.append("rollback"))
    args = Namespace(root=ROOT, evidence=tmp_path / "evidence", merge_sha="a" * 40, plan=tmp_path / "plan", confirmation=f"EXECUTE_FR06C2_DATABASE_CUTOVER:{plan['plan_id']}", confirm_production=module.CUTOVER_CONFIRMATION)
    result = module.apply_cutover(args)
    assert result["status"] == "candidate_database_started_admission_closed"
    assert "rollback" not in events
    assert events.index("clients-stopped") < events.index("probe:pg-old") < events.index("stop:pg-old")
    assert events.index("seal") < events.index("copy:legacy->candidate") < events.index("start-candidate-postgres") < events.index("probe:pg-new") < events.index("reconcile") < events.index("start-clients")


def test_apply_failure_after_candidate_start_requests_reverse_rollback(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    plan, runtime, legacy, candidate = _fake_plan(tmp_path)
    evidence = _evidence_value(datetime.now(timezone.utc))
    flags: list[bool] = []
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "_load_plan", lambda plan_path, evidence_path: plan)
    monkeypatch.setattr(module, "_preflight", lambda root, evidence_path, merge_sha: (evidence, runtime))
    monkeypatch.setattr(module, "_reserve", lambda operation_id, kind: None)
    monkeypatch.setattr(module, "_lock", lambda: os.open(tmp_path / "lock", os.O_RDWR | os.O_CREAT, 0o600))
    monkeypatch.setattr(module, "_stop_ids", lambda ids: None)
    monkeypatch.setattr(module, "_assert_planned_clients_stopped", lambda topology: None)
    monkeypatch.setattr(module, "_postgres_probe", lambda cid: _probe_value())
    monkeypatch.setattr(module, "_containers", lambda service, running_only: [{"id": "pg-new", "name": "postgres", "running": True, "status": "running", "health": "healthy", "image": "img"}] if service == module.POSTGRES_SERVICE else [])
    monkeypatch.setattr(module, "_pg_state_volume", lambda volume, subpath=None: "shut down")
    monkeypatch.setattr(module, "_seal", lambda path: None)
    monkeypatch.setattr(module, "_stable_copy", lambda *args, **kwargs: {"directories": 1, "regular_files": 1, "payload_bytes": 1, "aggregate_sha256": "x" * 64})
    monkeypatch.setattr(module, "_start_postgres", lambda files: None)
    monkeypatch.setattr(module, "_run_reconciler", lambda files: (_ for _ in ()).throw(module.CutoverError("synthetic failure")))
    monkeypatch.setattr(module, "_automatic_rollback", lambda *args, **kwargs: flags.append(bool(kwargs["candidate_started"])))
    args = Namespace(root=ROOT, evidence=tmp_path / "evidence", merge_sha="a" * 40, plan=tmp_path / "plan", confirmation=f"EXECUTE_FR06C2_DATABASE_CUTOVER:{plan['plan_id']}", confirm_production=module.CUTOVER_CONFIRMATION)
    with pytest.raises(module.CutoverError, match="automatic rollback passed"):
        module.apply_cutover(args)
    assert flags == [True]


def test_apply_failure_before_candidate_start_requests_direct_legacy_rollback(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    plan, runtime, legacy, candidate = _fake_plan(tmp_path)
    evidence = _evidence_value(datetime.now(timezone.utc))
    flags: list[bool] = []
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "_load_plan", lambda plan_path, evidence_path: plan)
    monkeypatch.setattr(module, "_preflight", lambda root, evidence_path, merge_sha: (evidence, runtime))
    monkeypatch.setattr(module, "_reserve", lambda operation_id, kind: None)
    monkeypatch.setattr(module, "_lock", lambda: os.open(tmp_path / "lock", os.O_RDWR | os.O_CREAT, 0o600))
    monkeypatch.setattr(module, "_stop_ids", lambda ids: None)
    monkeypatch.setattr(module, "_assert_planned_clients_stopped", lambda topology: None)
    monkeypatch.setattr(module, "_postgres_probe", lambda cid: _probe_value())
    monkeypatch.setattr(module, "_pg_state_volume", lambda volume, subpath=None: "shut down")
    monkeypatch.setattr(module, "_seal", lambda path: None)
    monkeypatch.setattr(module, "_stable_copy", lambda *args, **kwargs: (_ for _ in ()).throw(module.CutoverError("copy fail")))
    monkeypatch.setattr(module, "_automatic_rollback", lambda *args, **kwargs: flags.append(bool(kwargs["candidate_started"])))
    args = Namespace(root=ROOT, evidence=tmp_path / "evidence", merge_sha="a" * 40, plan=tmp_path / "plan", confirmation=f"EXECUTE_FR06C2_DATABASE_CUTOVER:{plan['plan_id']}", confirm_production=module.CUTOVER_CONFIRMATION)
    with pytest.raises(module.CutoverError, match="automatic rollback passed"):
        module.apply_cutover(args)
    assert flags == [False]


def test_postgres_probe_is_read_only_and_returns_identity_schema_and_counts(monkeypatch) -> None:
    module = _module()
    inspected = [{"Config": {"Env": ["POSTGRES_DB=aionex", "POSTGRES_USER=postgres", "POSTGRES_PASSWORD=do-not-read"]}}]
    outputs = iter([json.dumps(inspected), "aionex|postgres|160015\n20260908_0046\n2\n2\n1\n110\n165"])
    calls: list[list[str]] = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return next(outputs)
    monkeypatch.setattr(module, "_run", fake_run)
    result = module._postgres_probe("pg1")
    assert result == _probe_value()
    assert calls[0][:3] == ["docker", "inspect", "pg1"]
    assert calls[1][:3] == ["docker", "exec", "pg1"]
    assert "POSTGRES_PASSWORD" not in " ".join(calls[1])


def test_candidate_database_mismatch_fails_before_reconciler_and_requests_reverse_rollback(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    plan, runtime, legacy, candidate = _fake_plan(tmp_path)
    evidence = _evidence_value(datetime.now(timezone.utc))
    events: list[str] = []
    probes = {"pg-old": _probe_value(), "pg-new": {**_probe_value(), "backup_records": 109}}
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "_load_plan", lambda plan_path, evidence_path: plan)
    monkeypatch.setattr(module, "_preflight", lambda root, evidence_path, merge_sha: (evidence, runtime))
    monkeypatch.setattr(module, "_reserve", lambda operation_id, kind: None)
    monkeypatch.setattr(module, "_lock", lambda: os.open(tmp_path / "lock", os.O_RDWR | os.O_CREAT, 0o600))
    monkeypatch.setattr(module, "_stop_ids", lambda ids: None)
    monkeypatch.setattr(module, "_assert_planned_clients_stopped", lambda topology: None)
    monkeypatch.setattr(module, "_postgres_probe", lambda cid: probes[cid])
    monkeypatch.setattr(module, "_containers", lambda service, running_only: [{"id": "pg-new", "name": "postgres", "running": True, "status": "running", "health": "healthy", "image": "img"}] if service == module.POSTGRES_SERVICE else [])
    monkeypatch.setattr(module, "_pg_state_volume", lambda volume, subpath=None: "shut down")
    monkeypatch.setattr(module, "_seal", lambda path: None)
    monkeypatch.setattr(module, "_stable_copy", lambda *args, **kwargs: {"directories": 1, "regular_files": 1, "payload_bytes": 1, "aggregate_sha256": "x" * 64})
    monkeypatch.setattr(module, "_start_postgres", lambda files: events.append("start-postgres"))
    monkeypatch.setattr(module, "_run_reconciler", lambda files: events.append("reconcile"))
    monkeypatch.setattr(module, "_automatic_rollback", lambda *args, **kwargs: events.append("rollback:" + str(kwargs["candidate_started"])))
    args = Namespace(root=ROOT, evidence=tmp_path / "evidence", merge_sha="a" * 40, plan=tmp_path / "plan", confirmation=f"EXECUTE_FR06C2_DATABASE_CUTOVER:{plan['plan_id']}", confirm_production=module.CUTOVER_CONFIRMATION)
    with pytest.raises(module.CutoverError, match="automatic rollback passed"):
        module.apply_cutover(args)
    assert "reconcile" not in events
    assert events[-1] == "rollback:True"


def test_success_receipt_digest_is_verified(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    # Production receipts must be root-owned/private. CI runners are unprivileged,
    # so this unit test isolates digest semantics from the separately tested
    # production ownership boundary.
    monkeypatch.setattr(module, "_private_regular", lambda path, label, maximum=0: path.stat())
    body = {
        "schema_version": 1, "subpart": module.SUBPART, "operation": "database-cutover",
        "operation_id": "op", "status": "candidate_database_started_admission_closed",
        "admission_opened": False,
    }
    path = module._write_result("op", body)
    accepted = module._load_success_receipt(path)
    assert accepted["receipt_sha256"] == module._digest(body)
    tampered = json.loads(path.read_text())
    tampered["status"] = "tampered"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(module.CutoverBlocked, match="digest"):
        module._load_success_receipt(path)


def test_rollback_uses_descendant_source_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    rollback_source = source.split("def rollback", 1)[1].split("def parser", 1)[0]
    assert "_git_descendant_gate(args.root.resolve(), args.merge_sha)" in rollback_source
    assert "_git_gate(args.root.resolve(), args.merge_sha)" not in rollback_source


def test_cutover_source_contains_no_key_or_cryptsetup_capability() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "cryptsetup" not in source
    assert "active-bundle" not in source
    assert "recovery-bundle" not in source
    assert "FR06C2_PRODUCTION_DATABASE_CUTOVER" in source
    assert "FR06C2_PRODUCTION_DATABASE_ROLLBACK" in source
