from __future__ import annotations

import importlib.util
import io
import json
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06b4_vault_provision.py"
CONTRACT = ROOT / "docs/project/receipts/FR-06B4-production-vault-gates.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06B4-production-vault-gates.md"
DROP_IN = ROOT / "deploy/systemd/docker.service.d/30-aionex-fr06-vault-gate.conf"
HEADER_CUSTODY = ROOT / "scripts/security/fr06b4_header_custody.py"


def _module():
    spec = importlib.util.spec_from_file_location("fr06b4_vault_provision", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _header_module():
    spec = importlib.util.spec_from_file_location("fr06b4_header_custody", HEADER_CUSTODY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_fr06b4_fixed_vault_layout_matches_prior_contracts() -> None:
    contract = _json(CONTRACT)
    vaults = {row["role"]: row for row in contract["vaults"]}
    assert set(vaults) == {"asset-vault", "project-execution-vault"}
    assert vaults["asset-vault"]["preallocated_non_sparse_bytes"] == 64 * 1024**3
    assert vaults["project-execution-vault"]["preallocated_non_sparse_bytes"] == 32 * 1024**3
    assert vaults["asset-vault"]["mount_options"] == ["nodev", "nosuid", "noexec"]
    assert vaults["project-execution-vault"]["mount_options"] == ["nodev", "nosuid"]
    assert vaults["asset-vault"]["protected_root_count"] == 10
    assert vaults["project-execution-vault"]["protected_root_count"] == 1


def test_fr06b4_crypto_and_external_custody_are_fail_closed() -> None:
    crypto = _json(CONTRACT)["cryptography"]
    assert crypto == {
        "format": "LUKS2",
        "cipher": "aes-xts-plain64",
        "key_bits": 512,
        "pbkdf": "argon2id",
        "independent_active_and_recovery_key_per_vault": True,
        "exact_keyslot_count": 2,
        "active_and_recovery_bundles_must_be_distinct_external_library_items": True,
        "production_keys_on_unencrypted_root_allowed": False,
        "header_staging_allowed_only_on_tmpfs": True,
        "header_backups_must_be_uploaded_to_two_distinct_off_host_objects": True,
        "header_backups_must_not_share_custody_with_recovery_keys": True,
    }
    executor = _json(CONTRACT)["executor"]
    assert executor["accepts_key_material_only_from_tmpfs"] is True
    assert executor["prints_or_persists_key_material"] is False
    assert executor["maximum_plan_ttl_seconds"] == 900
    assert executor["single_use_plan"] is True
    assert executor["exclusive_nonblocking_lock"] is True
    custody = _json(CONTRACT)["header_custody_executor"]
    assert custody["accepts_key_material"] is False
    assert custody["requires_new_object_keys"] is True
    assert custody["verifies_head_metadata"] is True
    assert custody["verifies_full_object_readback_sha256"] is True


def test_fr06b4_never_authorizes_cutover_or_admission() -> None:
    contract = _json(CONTRACT)
    executor = contract["executor"]
    assert executor["stops_or_restarts_services"] is False
    assert executor["copies_live_data"] is False
    assert executor["opens_admission"] is False
    assert executor["changes_cloudflare"] is False
    assert contract["admission"]["remains_closed_by_this_subpart"] is True
    assert contract["admission"]["separate_owner_decision_required"] is True
    order = contract["production_gate_order"]
    assert order.index("protected PR head passes") < order.index("exact post-merge main passes")
    assert order.index("both LUKS2 header backups are independently uploaded and read-back verified off-host") < order.index("both recovery keys open their respective vaults and active keys reopen them")
    assert order[-1] == "a new independent owner decision is required before opening admission"


def test_docker_start_gate_checks_every_daemon_start() -> None:
    text = DROP_IN.read_text(encoding="utf-8")
    assert text.startswith("[Service]\n")
    assert "ExecStartPre=" in text
    assert "/opt/AIOS/scripts/security/fr06b4_vault_provision.py status --require-host-ready" in text
    assert "--active-bundle" not in text
    assert "--recovery-bundle" not in text
    restart = _json(CONTRACT)["docker_restart_gate"]
    assert restart["missing_mapper_or_mount_behavior"] == "docker.service fails closed before the daemon starts"
    assert restart["installation_is_separate_from_source_merge"] is True
    assert restart["docker_volume_options_checked_after_daemon_start_before_candidate_start"] is True
    host_gate_source = module_source_section("_verify_host_ready", "_verify_ready")
    assert "DOCKER_HOST" not in host_gate_source
    assert "subprocess" not in host_gate_source


def module_source_section(start: str, end: str) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    return source.split(f"def {start}", 1)[1].split(f"def {end}", 1)[0]


def test_post_boot_unlock_is_explicit_and_never_starts_docker(monkeypatch, tmp_path: Path) -> None:
    contract = _json(CONTRACT)
    executor = contract["executor"]
    assert "unlock" in executor["commands"]
    assert executor["post_boot_unlock_confirmation"] == "UNLOCK_FR06B4_PRODUCTION"
    assert executor["post_boot_unlock_starts_docker_or_services"] is False
    source = module_source_section("unlock_vaults", "apply_plan")
    assert "systemctl" not in source
    assert " start" not in source
    module = _module()
    with pytest.raises(module.ProvisionBlocked, match="unlock confirmation"):
        module.unlock_vaults(Namespace(confirmation="wrong", active_bundle=tmp_path / "active.json"))


def test_plan_is_digest_bound_short_lived_and_contains_no_secret_material(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_preflight",
        lambda args: ({"roots": [{}] * 11, "free_bytes": 200 * 1024**3}, "a" * 64, "b" * 64),
    )
    monkeypatch.setattr(module, "RUNTIME_ROOT", tmp_path)
    now = datetime.now(timezone.utc)
    plan_path = tmp_path / "plan-unit.json"
    args = Namespace(
        ttl_seconds=600,
        plan=plan_path,
        merge_sha="c" * 40,
        window_starts_at=(now - timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        window_ends_at=(now + timedelta(minutes=30)).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    result = module.create_plan(args)
    plan = _json(plan_path)
    assert result["confirmation"] == f"PROVISION-{plan['plan_id'][:16]}"
    assert module._digest({key: value for key, value in plan.items() if key != "plan_id"}) == plan["plan_id"]
    serialized = json.dumps(plan, sort_keys=True)
    for forbidden in ("asset_vault", "project_execution_vault", "passphrase", "key_material"):
        assert forbidden not in serialized
    assert plan["services_may_be_stopped_or_restarted"] is False
    assert plan["admission_remains_closed"] is True


def test_plan_rejects_long_ttl_or_non_runtime_path(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "RUNTIME_ROOT", tmp_path / "runtime")
    args = Namespace(ttl_seconds=901, plan=tmp_path / "plan-bad.json")
    with pytest.raises(module.ProvisionBlocked, match="TTL"):
        module.create_plan(args)
    args.ttl_seconds = 600
    with pytest.raises(module.ProvisionBlocked, match="fixed tmpfs runtime root"):
        module.create_plan(args)


def test_bundle_parser_requires_exact_independent_64_byte_hex_keys(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.setattr(module, "KEY_ROOT", tmp_path)
    monkeypatch.setattr(module, "_run", lambda argv, **kwargs: "tmpfs")
    path = tmp_path / "active.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "purpose": "active",
        "asset_vault": "11" * 64,
        "project_execution_vault": "22" * 64,
    }), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(module, "_private_regular", lambda path, label: path.stat())
    keys, digest = module._bundle(path, "active")
    assert set(keys) == {"asset_vault", "project_execution_vault"}
    assert all(len(value) == 64 for value in keys.values())
    assert len(digest) == 64
    value = json.loads(path.read_text(encoding="utf-8"))
    value["project_execution_vault"] = value["asset_vault"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.ProvisionBlocked, match="reuses key material"):
        module._bundle(path, "active")


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

        def head_bucket(self, **kwargs):
            return {}

        def head_object(self, *, Bucket, Key):
            if Key not in self.objects:
                raise MissingObject()
            return {"ContentLength": len(self.objects[Key]), "Metadata": self.metadata[Key]}

        def put_object(self, *, Bucket, Key, Body, ContentLength, ContentType, Metadata, IfNoneMatch):
            assert IfNoneMatch == "*"
            payload = Body.read()
            assert len(payload) == ContentLength
            self.objects[Key] = payload
            self.metadata[Key] = Metadata
            return {}

        def get_object(self, *, Bucket, Key):
            return {"Body": Body(self.objects[Key])}

    input_root = tmp_path / "headers"
    input_root.mkdir(mode=0o700)
    payloads = {
        "aionex-asset-vault.header": b"LUKS\xba\xbe" + b"a" * 64,
        "aionex-project-execution-vault.header": b"LUKS\xba\xbe" + b"p" * 64,
    }
    for name, payload in payloads.items():
        path = input_root / name
        path.write_bytes(payload)
        path.chmod(0o600)
    monkeypatch.setattr(module, "INPUT_ROOT", input_root)
    monkeypatch.setattr(
        module,
        "_credentials",
        lambda path: {
            "R2_BACKUP_ENDPOINT": "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com",
            "R2_BACKUP_BUCKET": "aionex-production-backups",
            "R2_BACKUP_ACCESS_KEY_ID": "not-returned",
            "R2_BACKUP_SECRET_ACCESS_KEY": "not-returned",
        },
    )
    result = module.upload(
        Namespace(generation="1" * 32, prefix="aionex-production", credentials=tmp_path / "unused"),
        client=FakeClient(),
    )
    assert result["status"] == "off_host_headers_verified"
    assert result["object_count"] == 2
    assert result["references_distinct"] is True
    assert result["full_readback_verified"] is True
    assert result["recovery_keys_stored_in_r2"] is False

    bad = input_root / "aionex-asset-vault.header"
    bad.write_bytes(b"not-luks")
    with pytest.raises(module.CustodyError, match="LUKS magic"):
        module._sha256(bad)


def test_receipt_documents_irreversible_boundaries() -> None:
    text = RECEIPT.read_text(encoding="utf-8")
    prose = " ".join(text.split())
    assert "does not itself stop services" in text
    assert "does not itself" in text
    assert "Opening admission requires a new," in text
    assert "independent owner decision." in text
    assert "15 percent" in text
    assert "Header or key references, rather than their contents" in prose
