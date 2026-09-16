from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-06C3C2-empty-vault-provisioning-contract.json"
PROVISION = ROOT / "scripts/security/fr06c3_vault_provision.py"
CUSTODY = ROOT / "scripts/security/fr06c3_header_custody.py"


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_c3c2_is_empty_vault_provisioning_only() -> None:
    c = _contract()
    assert c["subpart"] == "FR-06C3C2"
    assert c["implementation_status"] == "source_only_guarded_empty_vault_provisioning_and_header_custody"
    e = c["executor"]
    assert e["production_data_copy_capability"] is False
    assert e["service_stop_or_restart_capability"] is False
    assert e["redis_flush_capability"] is False
    assert e["log_move_capability"] is False
    assert e["cloudflare_change_capability"] is False


def test_exact_two_vaults_and_sizes() -> None:
    rows = {item["role"]: item for item in _contract()["vaults"]}
    assert set(rows) == {"local-backup-vault", "operations-vault"}
    assert rows["local-backup-vault"]["preallocated_bytes"] == 16 * 1024**3
    assert rows["operations-vault"]["preallocated_bytes"] == 8 * 1024**3
    assert rows["local-backup-vault"]["subpath"] == "backups"
    assert rows["operations-vault"]["subpath"] == "redis"
    assert rows["operations-vault"]["subpath_owner"] == "999:1000"
    for row in rows.values():
        assert row["mount_options"] == ["nodev", "nosuid", "noexec"]


def test_crypto_and_custody_are_external_and_independent() -> None:
    c = _contract()
    crypto = c["cryptography"]
    assert crypto["format"] == "LUKS2"
    assert crypto["cipher"] == "aes-xts-plain64"
    assert crypto["key_bits"] == 512
    assert crypto["pbkdf"] == "argon2id"
    assert crypto["exact_keyslot_count_each"] == 2
    assert crypto["production_keys_on_unencrypted_root_allowed"] is False
    assert crypto["key_inputs_tmpfs_only"] is True
    custody = c["header_custody"]
    assert custody["object_count"] == 2
    assert custody["new_object_keys_required"] is True
    assert custody["full_sha256_readback_required"] is True
    assert custody["recovery_keys_stored_in_r2"] is False


def test_provisioner_has_no_data_copy_or_runtime_mutation_commands() -> None:
    text = PROVISION.read_text(encoding="utf-8")
    assert '"rsync"' not in text
    assert '"docker", "stop"' not in text
    assert "FLUSHALL" not in text
    assert "systemctl" not in text
    assert "PROVISION_FR06C3_EMPTY_VAULTS" in text
    assert "/dev/shm/aionex-fr06c3-keys" in text
    assert '"production_backup_data_read_or_copied": False' in text
    assert '"production_redis_data_read_or_copied": False' in text
    assert '"production_redis_flushed": False' in text


def test_header_custody_accepts_two_fixed_headers_only() -> None:
    text = CUSTODY.read_text(encoding="utf-8")
    assert '"local-backup-vault": "aionex-local-backup-vault.header"' in text
    assert '"operations-vault": "aionex-operations-vault.header"' in text
    assert '"object_count": 2' in text
    assert 'len({item["reference"] for item in objects}) == 2' in text
    assert '"recovery_keys_stored_in_r2": False' in text
    assert "/run/aionex-fr06c3-headers" in text


def test_scope_keeps_production_untouched_by_source_merge() -> None:
    s = _contract()["scope_boundary"]
    assert s["production_execution_by_source_merge"] is False
    assert s["production_backup_data_read_or_copied"] is False
    assert s["production_redis_data_read_or_copied"] is False
    assert s["production_redis_flushed"] is False
    assert s["production_logs_moved"] is False
    assert s["production_services_stopped_or_restarted"] is False
    assert s["admission_opened"] is False
    assert s["cloudflare_changed"] is False


def test_post_boot_unlock_is_tmpfs_only_and_never_starts_docker() -> None:
    c = _contract()
    e = c["executor"]
    assert "unlock" in e["commands"]
    assert e["post_boot_unlock_confirmation"] == "UNLOCK_FR06C3_VAULTS"
    assert e["post_boot_unlock_starts_docker_or_services"] is False
    text = PROVISION.read_text(encoding="utf-8")
    assert 'UNLOCK_CONFIRMATION = "UNLOCK_FR06C3_VAULTS"' in text
    assert 'Docker must be stopped before C3 vault unlock' in text
    assert '"services_started_or_restarted": False' in text
    assert '"key_material_persisted": False' in text


def test_docker_gate_is_source_only_and_host_ready_not_consumer_bound() -> None:
    c = _contract()["docker_restart_gate"]
    assert c["missing_mapper_behavior"].startswith("Docker fails closed")
    assert c["unlocks_keys"] is False
    assert c["source_merge_installs_drop_in"] is False
    dropin = ROOT / c["repository_drop_in"]
    assert dropin.read_text(encoding="utf-8") == (
        "[Service]\n"
        "ExecStartPre=/usr/bin/python3 /opt/AIOS/scripts/security/fr06c3_vault_provision.py status --require-host-ready\n"
    )
    text = PROVISION.read_text(encoding="utf-8")
    assert '"validation": "FR06C3_VAULTS_HOST_READY"' in text
    assert "_verify_all_host_ready() if args.require_host_ready" in text
