from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06c2_database_cutover.py"
CONTRACT = ROOT / "docs/project/receipts/FR-06C2D-database-restart-gate.json"
DROPIN = ROOT / "deploy/systemd/docker.service.d/31-aionex-fr06-database-vault-gate.conf"


def _module():
    spec = importlib.util.spec_from_file_location("fr06c2d_restart", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docker_gate_is_fail_closed_and_keyless() -> None:
    value = json.loads(CONTRACT.read_text())
    gate = value["docker_gate"]
    assert gate["unlocks_keys"] is False
    assert gate["missing_mapper_behavior"].startswith("docker fails closed")
    text = DROPIN.read_text()
    assert "ExecStartPre=" in text
    assert "fr06c2_database_vault_provision.py status --require-host-ready" in text
    assert "unlock" not in text


def test_parser_exposes_guarded_start() -> None:
    module = _module()
    parser = module.parser()
    args = parser.parse_args([
        "guarded-start", "--receipt", "/tmp/receipt.json", "--nonce", "0123456789abcdef",
        "--confirmation", "x", "--confirm-production", module.START_CONFIRMATION,
    ])
    assert args.command == "guarded-start"


def test_guarded_start_rejects_bad_confirmations(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    receipt = {"receipt_sha256": "a" * 64, "merge_sha": "b" * 40, "topology": {}, "legacy_source": str(tmp_path), "candidate_source": str(tmp_path)}
    monkeypatch.setattr(module, "_load_success_receipt", lambda path: receipt)
    args = Namespace(root=ROOT, receipt=tmp_path / "r", nonce="0123456789abcdef", confirmation="bad", confirm_production=module.START_CONFIRMATION)
    with pytest.raises(module.CutoverBlocked, match="confirmation"):
        module.guarded_start(args)


def test_guarded_start_orders_acceptance_before_clients(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    legacy = tmp_path / "legacy"; candidate = tmp_path / "candidate"
    legacy.mkdir(); candidate.mkdir()
    (legacy / "PG_VERSION").write_text("16\n"); (candidate / "PG_VERSION").write_text("16\n")
    topology = {"active_clients": {"backend": ["old-backend"]}}
    accepted = {"database":"aionex","user":"postgres","server_version_num":"160015","alembic_version":"x","organizations":2,"users":2,"project_executions":1,"backup_records":1,"public_table_count":10}
    prior = {"receipt_sha256":"a"*64,"merge_sha":"b"*40,"topology":topology,"legacy_source":str(legacy),"candidate_source":str(candidate),"database_acceptance":{"candidate":accepted}}
    events: list[str] = []
    monkeypatch.setattr(module, "_load_success_receipt", lambda path: prior)
    monkeypatch.setattr(module, "_git_descendant_gate", lambda root, sha: events.append("git"))
    monkeypatch.setattr(module, "_validate_candidate_host_ready", lambda root: events.append("host-ready"))
    monkeypatch.setattr(module, "_containers", lambda service, running_only: [] if service != module.POSTGRES_SERVICE or "started" not in events else [{"id":"pg","health":"healthy"}])
    monkeypatch.setattr(module, "_lock", lambda: 99)
    monkeypatch.setattr(module, "_reserve", lambda op, kind: events.append("reserve"))
    monkeypatch.setattr(module.fcntl, "flock", lambda *a: None)
    monkeypatch.setattr(module.os, "close", lambda fd: None)
    entries={"entries":[["PG_VERSION","f",0,0,0,"3:x"]]}
    monkeypatch.setattr(module, "_manifest_entries", lambda root, path: entries)
    monkeypatch.setattr(module, "_sealed", lambda path: True)
    monkeypatch.setattr(module, "_start_postgres", lambda files: events.append("started"))
    monkeypatch.setattr(module, "_postgres_probe", lambda cid: events.append("probe") or accepted)
    monkeypatch.setattr(module, "_run_reconciler", lambda files: events.append("reconciler"))
    monkeypatch.setattr(module, "_start_clients", lambda files, topo: events.append("clients"))
    monkeypatch.setattr(module, "_candidate_topology_matches", lambda topo: True)
    monkeypatch.setattr(module, "_write_result", lambda op, body: tmp_path / "result.json")
    nonce="0123456789abcdef"
    opid=module._digest({"operation":"database-guarded-start","receipt":prior["receipt_sha256"],"nonce":nonce})
    args=Namespace(root=module.PRODUCTION_ROOT,receipt=tmp_path/"r",nonce=nonce,confirmation=f"START_FR06C2_DATABASE:{opid}",confirm_production=module.START_CONFIRMATION)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    result=module.guarded_start(args)
    assert result["status"] == "candidate_database_started_admission_closed"
    assert events.index("probe") < events.index("reconciler") < events.index("clients")


def test_contract_keeps_admission_closed() -> None:
    value=json.loads(CONTRACT.read_text())
    assert value["scope_boundary"]["admission_opened"] is False
    assert value["scope_boundary"]["cloudflare_changed"] is False
    assert value["scope_boundary"]["legacy_pgdata_deleted"] is False
