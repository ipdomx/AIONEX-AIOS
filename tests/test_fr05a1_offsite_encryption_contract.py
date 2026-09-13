import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs" / "project" / "receipts" / "FR-05A1-client-side-encryption-contract.json"
RECEIPT = ROOT / "docs" / "project" / "receipts" / "FR-05A1-client-side-encryption-contract.md"
OFFSITE = ROOT / "web-dashboard" / "backend" / "app" / "services" / "offsite_backup.py"
PLAN = ROOT / "docs" / "project" / "PLAN.json"


def test_fr05a1_contract_requires_client_side_encryption_before_rollout() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["implementation_status"] == "design_contract_only"
    assert policy["current_state"]["client_side_encryption"] == "not_implemented_yet"
    assert policy["current_state"]["provider_at_rest_encryption_is_sufficient_for_fr05"] is False
    required = policy["required_before_encrypted_rollout"]
    assert required["encrypt_database_dump_before_upload"] is True
    assert required["encrypt_asset_snapshot_before_upload"] is True
    assert required["wrong_key_restore_test"] is True
    assert required["tampered_ciphertext_restore_test"] is True
    assert required["no_plaintext_key_material_in_git_reports_logs_or_backup_artifacts"] is True


def test_fr05a1_key_material_is_separated_from_backup_payloads_and_reports() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    separation = policy["key_separation_contract"]
    forbidden = "\n".join(separation["forbidden_locations"])
    assert "Git repository" in forbidden
    assert "R2 backup payload prefix" in forbidden
    assert "database dump" in forbidden
    assert "asset snapshot tar" in forbidden
    assert "container image layers" in forbidden
    must_not = "\n".join(separation["reports_must_not_record"])
    assert "raw key material" in must_not
    assert "decryption material" in must_not
    may = "\n".join(separation["reports_may_record"])
    assert "key_id" in may
    assert "algorithm" in may


def test_fr05a1_current_offsite_code_is_readback_only_not_client_side_encryption() -> None:
    source = OFFSITE.read_text(encoding="utf-8")
    assert "full SHA-256 readback" in source
    assert "automatic AES-256 encryption at rest" in source
    replicator = source.split("class OffsiteBackupReplicator", 1)[1]
    assert "client-side" not in replicator
    assert "R2_BACKUP_ENCRYPTION" not in source


def test_fr05a1_plan_keeps_implementation_and_independent_restore_as_later_slices() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    fr05 = next(batch for batch in plan["batches"] if batch["id"] == "FR-05")
    sub = "\n".join(fr05["sub_batches"])
    assert "FR-05B تنفيذ تشفير النسخ" in sub
    assert "FR-05C دمج ونشر المسار المشفر" in sub
    assert "FR-05D استعادة مستقلة غير فارغة" in sub
    assert fr05["depends_on"] == ["FR-04"]


def test_fr05a1_receipt_states_no_runtime_or_cloudflare_change() -> None:
    text = RECEIPT.read_text(encoding="utf-8")
    assert "design/contract slice only" in text
    assert "does not change Cloudflare" in text
    assert "backup-worker runtime" in text
    assert "production backup behavior" in text
