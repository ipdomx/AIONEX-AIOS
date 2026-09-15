from __future__ import annotations

import importlib.util
import io
import json
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06c2_database_vault_provision.py"
HEADER = ROOT / "scripts/security/fr06c2_database_header_custody.py"
CONTRACT = ROOT / "docs/project/receipts/FR-06C2B-production-vault-gates.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C2B-production-vault-gates.md"
DROP_IN = ROOT / "deploy/systemd/docker.service.d/31-aionex-fr06c2-database-gate.conf"
GIB = 1024**3


def _module():
    spec = importlib.util.spec_from_file_location("fr06c2b_provision", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _header_module():
    spec = importlib.util.spec_from_file_location("fr06c2b_header", HEADER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def test_fixed_database_vault_layout_and_scope_boundary() -> None:
    value = _json(CONTRACT)
    vault = value["vault"]
    assert value["subpart"] == "FR-06C2B"
    assert value["implementation_status"] == "source_only_provisioning_recovery_and_boot_gate"
    assert vault["role"] == "database-vault"
    assert vault["preallocated_non_sparse_bytes"] == 16 * GIB
    assert vault["mapper"] == "/dev/mapper/aionex-database-vault"
    assert vault["target_subpath"] == "pgdata"
    assert vault["filesystem_label"] == "AIONEX06_DB"
    assert vault["mount_options"] == ["nodev", "nosuid", "noexec"]
    scope = value["scope_boundary"]
    assert scope["production_pgdata_read_or_copied"] is False
    assert scope["production_postgres_stopped"] is False
    assert scope["database_clients_stopped"] is False
    assert scope["candidate_postgres_started"] is False
    assert scope["docker_gate_installed"] is False
    assert scope["parent_fr06_completed"] is False


def test_crypto_and_fresh_recovery_are_fail_closed() -> None:
    value = _json(CONTRACT)
    crypto = value["cryptography"]
    assert crypto["format"] == "LUKS2"
    assert crypto["cipher"] == "aes-xts-plain64"
    assert crypto["key_bits"] == 512
    assert crypto["pbkdf"] == "argon2id"
    assert crypto["independent_active_and_recovery_keys"] is True
    assert crypto["exact_keyslot_count"] == 2
    assert crypto["production_keys_on_unencrypted_root_allowed"] is False
    recovery = value["fresh_recovery_evidence"]
    assert recovery["client_side_encrypted_r2_backup_required"] is True
    assert recovery["independent_restore_validation_required"] is True
    assert recovery["maximum_age_seconds"] == 3600
    assert recovery["raw_key_material_forbidden"] is True


def test_executor_cannot_copy_pgdata_or_restart_services() -> None:
    executor = _json(CONTRACT)["executor"]
    assert executor["stops_or_restarts_services"] is False
    assert executor["copies_production_pgdata"] is False
    assert executor["changes_cloudflare"] is False
    assert executor["accepts_key_material_only_from_tmpfs"] is True
    assert executor["prints_or_persists_key_material"] is False
    assert executor["single_use_plan"] is True
    assert executor["exclusive_nonblocking_lock"] is True
    text = RECEIPT.read_text(encoding="utf-8")
    assert "never authorizes PGDATA movement" in text
    assert "must not be installed during C2B provisioning" in text


def test_database_docker_gate_is_shipped_but_install_is_deferred() -> None:
    text = DROP_IN.read_text(encoding="utf-8")
    assert text.startswith("[Service]\n")
    assert "fr06c2_database_vault_provision.py status --require-host-ready" in text
    assert "--active-bundle" not in text
    gate = _json(CONTRACT)["docker_restart_gate"]
    assert gate["installation_during_c2b_provisioning_allowed"] is False
    assert "Only after PostgreSQL production cutover" in gate["installation_gate"]


def test_plan_is_digest_bound_short_lived_and_contains_no_secret_material(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(
        module,
        "_preflight",
        lambda args: ({"legacy": {"volume": module.LEGACY_VOLUME}, "free_bytes": 40 * GIB}, "a" * 64, "b" * 64),
    )
    plan_path = tmp_path / "plan-unit.json"
    evidence_path = tmp_path / "evidence"
    evidence_path.write_text("{}", encoding="utf-8")
    args = Namespace(ttl_seconds=600, plan=plan_path, merge_sha="c" * 40, evidence=evidence_path, active_bundle=tmp_path / "active", recovery_bundle=tmp_path / "recovery", root=ROOT)
    result = module.create_plan(args)
    plan = _json(plan_path)
    assert result["confirmation"] == f"PROVISION-{plan['plan_id'][:16]}"
    body = {k: v for k, v in plan.items() if k != "plan_id"}
    assert module._digest(body) == plan["plan_id"]
    serialized = json.dumps(plan, sort_keys=True)
    assert "database_vault" not in serialized
    assert "key_material" not in serialized
    assert plan["services_may_be_stopped_or_restarted"] is False
    assert plan["production_pgdata_copy_permitted"] is False
    assert plan["admission_opened"] is False


def test_plan_rejects_long_ttl_or_non_runtime_path(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "RUNTIME_ROOT", tmp_path / "runtime")
    args = Namespace(ttl_seconds=901, plan=tmp_path / "plan-bad.json")
    with pytest.raises(module.ProvisionBlocked, match="TTL"):
        module.create_plan(args)
    args.ttl_seconds = 600
    with pytest.raises(module.ProvisionBlocked, match="fixed runtime root"):
        module.create_plan(args)


def test_bundle_requires_exact_64_byte_database_key(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "KEY_ROOT", tmp_path)
    monkeypatch.setattr(module, "_run", lambda argv, **kwargs: "tmpfs")
    monkeypatch.setattr(module, "_private_regular", lambda path, label, **kwargs: path.stat())
    path = tmp_path / "active.json"
    path.write_text(json.dumps({"schema_version": 1, "purpose": "active", "database_vault": "11" * 64}), encoding="utf-8")
    path.chmod(0o600)
    key, digest = module._bundle(path, "active")
    assert len(key) == 64
    assert len(digest) == 64
    value = _json(path)
    value["database_vault"] = "11" * 63
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.ProvisionBlocked, match="length"):
        module._bundle(path, "active")


def test_fresh_recovery_evidence_rejects_raw_secret_fields(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "_private_regular", lambda path, label, **kwargs: path.stat())
    now = datetime.now(timezone.utc)
    evidence = {
        "schema_version": 1,
        "subpart": "FR-06C2B",
        "environment": "production",
        "observed_at": _z(now),
        "production_authorization": True,
        "source": {"merge_sha": "a" * 40, "protected_pr_checks_passed": True, "post_merge_main_checks_passed": True},
        "recovery": {"backup_id": "backup", "backup_status": "completed", "offsite_status": "completed", "restore_run_id": "restore", "restore_status": "completed", "restore_validated": True, "restore_offsite_validated": True, "restore_completed_at": _z(now)},
        "approvals": {"owner_authorized": True, "window_starts_at": _z(now - timedelta(minutes=1)), "window_ends_at": _z(now + timedelta(minutes=20)), "active_key_ref": "offline://custody/active", "recovery_key_ref": "offline://custody/recovery"},
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    path.chmod(0o600)
    assert module._evidence(path, "a" * 40)["recovery"]["restore_validated"] is True
    evidence["recovery"]["secret"] = "never-allowed"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(module.ProvisionBlocked, match="embedded secret material"):
        module._evidence(path, "a" * 40)


def test_unlock_rejects_wrong_confirmation_before_any_operation(tmp_path: Path) -> None:
    module = _module()
    with pytest.raises(module.ProvisionBlocked, match="confirmation"):
        module.unlock(Namespace(confirmation="wrong", active_bundle=tmp_path / "missing"))


def test_header_custody_requires_luks_magic_and_full_readback(monkeypatch, tmp_path: Path) -> None:
    module = _header_module()

    class MissingObject(Exception):
        def __init__(self) -> None:
            self.response = {"Error": {"Code": "404"}}

    class Body(io.BytesIO):
        pass

    class FakeClient:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}
            self.metadata: dict[str, dict[str, str]] = {}
        def head_bucket(self, **kwargs): return {}
        def head_object(self, *, Bucket, Key):
            if Key not in self.objects: raise MissingObject()
            return {"ContentLength": len(self.objects[Key]), "Metadata": self.metadata[Key]}
        def put_object(self, *, Bucket, Key, Body, ContentLength, ContentType, Metadata, IfNoneMatch):
            assert IfNoneMatch == "*"
            payload = Body.read(); assert len(payload) == ContentLength
            self.objects[Key] = payload; self.metadata[Key] = Metadata; return {}
        def get_object(self, *, Bucket, Key): return {"Body": Body(self.objects[Key])}

    input_root = tmp_path / "headers"; input_root.mkdir(mode=0o700)
    header = input_root / "aionex-database-vault.header"
    header.write_bytes(b"LUKS\xba\xbe" + b"d" * 64); header.chmod(0o600)
    monkeypatch.setattr(module, "INPUT_ROOT", input_root)
    monkeypatch.setattr(module, "_credentials", lambda path: {
        "R2_BACKUP_ENDPOINT": "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com",
        "R2_BACKUP_BUCKET": "aionex-production-backups",
        "R2_BACKUP_ACCESS_KEY_ID": "not-returned",
        "R2_BACKUP_SECRET_ACCESS_KEY": "not-returned",
    })
    result = module.upload(Namespace(generation="1" * 32, prefix="aionex-production", credentials=tmp_path / "unused"), client=FakeClient())
    assert result["status"] == "off_host_headers_verified"
    assert result["object_count"] == 1
    assert result["references_distinct"] is True
    assert result["full_readback_verified"] is True
    assert result["recovery_keys_stored_in_r2"] is False
    header.write_bytes(b"not-luks")
    with pytest.raises(module.CustodyError, match="LUKS magic"):
        module._sha256(header)
