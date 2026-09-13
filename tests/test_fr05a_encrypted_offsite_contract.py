from pathlib import Path


def test_fr05a_receipt_and_runtime_contract_are_tracked():
    root = Path(__file__).resolve().parents[1]
    service = (root / "web-dashboard/backend/app/services/offsite_encryption.py").read_text()
    compose = (root / "web-dashboard/docker-compose.production.yml").read_text()
    receipt = (root / "docs/project/receipts/FR-05A-encrypted-offsite-contract.md").read_text()
    assert "AES-256-GCM" in service
    assert "BACKUP_OFFSITE_ENCRYPTION_REQUIRED" in compose
    assert "separate root-owned host file" in receipt
    assert "not deployed" in receipt


def test_fr05a_key_material_is_not_embedded_in_tracked_config():
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "deploy/production/.env.production.example",
        root / "web-dashboard/docker-compose.production.yml",
        root / "deploy/production/docker-compose.production.yml",
    ]
    text = "\n".join(path.read_text() for path in files)
    assert "BACKUP_OFFSITE_ENCRYPTION_KEY_ID" in text
    assert "AIOS_R2_BACKUP_ENCRYPTION_KEY_HOST_FILE" in text
    assert "BACKUP_OFFSITE_ENCRYPTION_KEY=" not in text
