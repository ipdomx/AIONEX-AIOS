from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SETTINGS = ROOT / "web-dashboard" / "backend" / "app" / "core" / "config.py"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"
ENTRYPOINT = ROOT / "web-dashboard" / "backend" / "scripts" / "docker-entrypoint.sh"


def _service_block(name: str, next_name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"\n  {name}:", 1)[1].split(f"\n\n  {next_name}:", 1)[0]


def test_fr04b3_backup_worker_mounts_media_assets_only_as_new_root() -> None:
    init = _service_block("backup-asset-root-init", "backup-worker")
    backup = _service_block("backup-worker", "communication-worker")
    assert "media_asset_data:/var/lib/aionex/media-assets:rw" in init
    assert "media_asset_data:/var/lib/aionex/media-assets:ro" in backup
    assert 'BACKUP_MEDIA_ASSETS_ENABLED: "true"' in backup
    assert "MEDIA_STORAGE_ROOT: /var/lib/aionex/media-assets" in backup
    assert "project_npm_cache_data" not in backup
    assert "studio_asset_data" not in backup
    assert "portal_asset_data" not in backup


def test_fr04b3_media_settings_and_snapshot_root_are_explicit() -> None:
    settings = SETTINGS.read_text(encoding="utf-8")
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    assert "BACKUP_MEDIA_ASSETS_ENABLED" in settings
    assert "MEDIA_STORAGE_ROOT" in settings
    assert '"media_asset_data"' in snapshot
    assert "Media asset" in snapshot
    assert "BACKUP_MEDIA_ASSETS_ENABLED" in snapshot


def test_fr04b3_entrypoint_accepts_read_only_media_asset_root() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "Unable to prepare private media asset root" in entrypoint
    assert "Private media asset root is not owned or permissioned correctly" in entrypoint
    assert "media_storage_meta" in entrypoint
