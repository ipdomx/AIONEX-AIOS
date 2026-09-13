import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/project/receipts/FR-05A2-crypto-keyring-envelope-contract.json"
OFFSITE = ROOT / "web-dashboard/backend/app/services/offsite_backup.py"


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_fr05a2_selects_existing_pipeline_not_restic_replacement() -> None:
    contract = _contract()
    decision = contract["architecture_decision"]
    assert decision["selected_path"] == "extend_existing_offsite_backup_pipeline"
    assert decision["restic_evaluation"] == "not_selected_for_fr05"
    assert decision["cloudflare_configuration_change_required"] is False


def test_fr05a2_locks_streaming_aes256_gcm_parameters() -> None:
    crypto = _contract()["algorithm_contract"]
    assert crypto["algorithm"] == "AES-256-GCM"
    assert crypto["key_bytes"] == 32
    assert crypto["nonce_bytes"] == 12
    assert crypto["tag_bytes"] == 16
    assert crypto["streaming_required"] is True
    assert crypto["whole_file_plaintext_buffering_for_database_or_asset_snapshot"] is False
    assert set(crypto["encrypted_roles"]) == {"database", "platform_asset_snapshot", "manifest"}


def test_fr05a2_envelope_binds_object_identity_and_plaintext_evidence() -> None:
    envelope = _contract()["envelope_contract"]
    bound = set(envelope["associated_data_must_bind"])
    assert {"backup_id", "object_role", "r2_object_key", "key_id"}.issubset(bound)
    assert {"plaintext_sha256", "plaintext_size_bytes"}.issubset(bound)
    assert "raw key material" in envelope["r2_metadata_must_not_contain"]
    assert "decryption key" in envelope["r2_metadata_must_not_contain"]


def test_fr05a2_keyring_is_separate_root_only_and_never_uploaded() -> None:
    keyring = _contract()["keyring_contract"]
    assert keyring["host_path"] != "/root/.config/aionex/r2-backup/credentials.env"
    assert keyring["separate_from_r2_credentials_file"] is True
    assert keyring["never_uploaded_to_r2"] is True
    assert keyring["never_baked_into_image"] is True
    assert keyring["host_mode"] == "0400 root-only"
    assert keyring["runtime_copy_mode"] == "0400 aionex-only"
    forbidden = set(keyring["secret_fields_forbidden_from_reports_logs_git"])
    assert {"key_b64", "raw key bytes"}.issubset(forbidden)


def test_fr05a2_rotation_cannot_orphan_retained_backups() -> None:
    rotation = _contract()["rotation_contract"]
    assert rotation["new_backups_use_only_active_key"] is True
    assert rotation["previous_active_key_becomes_decrypt_only"] is True
    conditions = "\n".join(rotation["old_key_deletion_requires"])
    assert "no retained" in conditions
    assert "retention cleanup" in conditions
    assert rotation["automatic_reencryption_of_old_backups"] is False
    assert "unrecoverable-backup incident" in rotation["lost_required_key"]


def test_fr05a2_new_object_names_do_not_reuse_plaintext_names() -> None:
    names = _contract()["object_naming_contract"]
    assert names["database"].endswith(".aex1")
    assert names["platform_asset_snapshot"].endswith(".aex1")
    assert names["manifest"].endswith(".aex1")
    assert "must not upload plaintext" in names["legacy_plaintext_r2_objects"]


def test_fr05a2_scope_does_not_overclaim_local_or_disk_encryption() -> None:
    scope = _contract()["scope_boundary"]
    claims = "\n".join(scope["fr05_does_not_claim"])
    assert "full-disk encryption" in claims
    assert "local backup_data encryption at rest" in claims
    assert scope["local_at_rest_follow_up"] == "FR-06"


def test_fr05a2_requires_direct_cryptography_runtime_dependency_before_rollout() -> None:
    dependency = _contract()["implementation_dependency_contract"]
    assert dependency["cryptography_must_be_direct_runtime_dependency"] is True
    assert dependency["must_not_rely_on_pyjwt_crypto_transitive_install"] is True
    assert "FR-05B" in dependency["dependency_pin_added_in"]


def test_fr05a2_does_not_claim_runtime_implementation_yet() -> None:
    contract = _contract()
    assert contract["implementation_status"] == "design_contract_only"
    source = OFFSITE.read_text(encoding="utf-8")
    assert "AIONEX-R2-ENC" not in source
    assert "backup-encryption-keyring" not in source
