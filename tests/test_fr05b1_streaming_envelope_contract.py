from pathlib import Path


def test_fr05b1_runtime_contract_matches_locked_fr05a2_design():
    root = Path(__file__).resolve().parents[1]
    service = (root / "web-dashboard/backend/app/services/offsite_encryption.py").read_text()
    compose = (root / "web-dashboard/docker-compose.production.yml").read_text()
    receipt = (root / "docs/project/receipts/FR-05B1-streaming-envelope-keyring.md").read_text()
    runtime = (root / "web-dashboard/backend/requirements-runtime.txt").read_text()
    assert 'b"AIONEX-R2-ENC"' in service
    assert '"AES-256-GCM"' in service
    assert "OffsiteEncryptionKeyring" in service
    assert "BACKUP_OFFSITE_ENCRYPTION_REQUIRED" in compose
    assert "/root/.config/aionex/backup-encryption/keyring.json" in compose
    assert "cryptography==" in runtime
    assert "not wired to R2 yet" in receipt


def test_fr05b1_key_material_is_not_embedded_in_tracked_config():
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "deploy/production/.env.production.example",
        root / "web-dashboard/docker-compose.production.yml",
        root / "deploy/production/docker-compose.production.yml",
    ]
    text = "\n".join(path.read_text() for path in files)
    assert "AIOS_BACKUP_ENCRYPTION_KEYRING_HOST_FILE" in text
    assert "BACKUP_OFFSITE_ENCRYPTION_KEYRING_FILE" in text
    assert "key_b64" not in text
    assert "BACKUP_OFFSITE_ENCRYPTION_KEY=" not in text
