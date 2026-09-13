from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SETTINGS = ROOT / "web-dashboard" / "backend" / "app" / "core" / "config.py"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"


def _service_block(name: str, next_name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"\n  {name}:", 1)[1].split(f"\n\n  {next_name}:", 1)[0]


def test_fr04b9_backup_worker_mounts_security_sources_read_only_only() -> None:
    init = _service_block("backup-asset-root-init", "backup-worker")
    backup = _service_block("backup-worker", "communication-worker")
    assert "/var/lib/aionex/security-sources" in init
    assert "security_source_data:/var/lib/aionex/security-sources:rw" in init
    assert 'BACKUP_SECURITY_SOURCES_ENABLED: "true"' in backup
    assert "SECURITY_SOURCE_ROOT: /var/lib/aionex/security-sources" in backup
    assert "security_source_data:/var/lib/aionex/security-sources:ro" in backup
    assert "security_tool_cache_data" not in backup
    assert "project_npm_cache_data" not in backup


def test_fr04b9_security_source_settings_and_snapshot_are_explicit() -> None:
    settings = SETTINGS.read_text(encoding="utf-8")
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    assert "BACKUP_SECURITY_SOURCES_ENABLED" in settings
    assert "SECURITY_SOURCE_ROOT" in settings
    assert '"security_source_data"' in snapshot
    assert "Security source" in snapshot
    assert "BACKUP_SECURITY_SOURCES_ENABLED" in snapshot
