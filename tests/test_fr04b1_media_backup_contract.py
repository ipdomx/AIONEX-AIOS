from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_backup_worker_mounts_media_read_only() -> None:
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        start = text.index("  backup-worker:")
        end = text.find("\n  communication-worker:", start)
        block = text[start:] if end < 0 else text[start:end]
        assert 'BACKUP_MEDIA_ASSETS_ENABLED: "true"' in block
        assert "MEDIA_STORAGE_ROOT: /var/lib/aionex/media-assets" in block
        assert "media_asset_data:/var/lib/aionex/media-assets:ro" in block


def test_media_backup_is_integrated_with_worker_and_r2() -> None:
    worker = (ROOT / "web-dashboard/backend/app/services/backup_worker.py").read_text(encoding="utf-8")
    offsite = (ROOT / "web-dashboard/backend/app/services/offsite_backup.py").read_text(encoding="utf-8")
    assert '"media_snapshot": media_snapshot_evidence' in worker
    assert "media_snapshot=media_snapshot" in worker
    assert "offsite_media_snapshot_validated" in worker
    assert 'self._key(backup_id, "media-assets.tar")' in offsite
    assert '"media_snapshot": media_evidence' in offsite
