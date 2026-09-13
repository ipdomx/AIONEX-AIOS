from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SETTINGS = ROOT / "web-dashboard" / "backend" / "app" / "core" / "config.py"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"
ENTRYPOINT = ROOT / "web-dashboard" / "backend" / "scripts" / "docker-entrypoint.sh"


def _service_block(name: str, next_name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"\n  {name}:", 1)[1].split(f"\n\n  {next_name}:", 1)[0]


def test_fr04b5_backup_worker_mounts_portal_assets_read_only_only() -> None:
    init = _service_block("backup-asset-root-init", "backup-worker")
    backup = _service_block("backup-worker", "communication-worker")
    assert "portal_asset_data:/var/lib/aionex/portal-assets:rw" in init
    assert 'BACKUP_PORTAL_ASSETS_ENABLED: "true"' in backup
    assert "PORTAL_ASSET_ROOT: /var/lib/aionex/portal-assets" in backup
    assert "portal_asset_data:/var/lib/aionex/portal-assets:ro" in backup
    assert "project_npm_cache_data" not in backup
    assert "security_source_data" not in backup
    assert "security_remediation_data" not in backup


def test_fr04b5_portal_settings_snapshot_and_entrypoint_are_explicit() -> None:
    settings = SETTINGS.read_text(encoding="utf-8")
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "BACKUP_PORTAL_ASSETS_ENABLED" in settings
    assert '"portal_asset_data"' in snapshot
    assert "Portal asset" in snapshot
    assert "BACKUP_PORTAL_ASSETS_ENABLED" in snapshot
    assert "Unable to prepare private portal asset root" in entrypoint
    assert "Private portal asset root is not owned or permissioned correctly" in entrypoint
    assert "portal_asset_meta" in entrypoint
