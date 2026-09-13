from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SETTINGS = ROOT / "web-dashboard" / "backend" / "app" / "core" / "config.py"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"
ENTRYPOINT = ROOT / "web-dashboard" / "backend" / "scripts" / "docker-entrypoint.sh"


def _service_block(name: str, next_name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"\n  {name}:", 1)[1].split(f"\n\n  {next_name}:", 1)[0]


def test_fr04b10_backup_worker_mounts_security_remediations_read_only_only() -> None:
    init = _service_block("backup-asset-root-init", "backup-worker")
    backup = _service_block("backup-worker", "communication-worker")
    assert "/var/lib/aionex/security-remediations" in init
    assert "security_remediation_data:/var/lib/aionex/security-remediations:rw" in init
    assert 'BACKUP_SECURITY_REMEDIATIONS_ENABLED: "true"' in backup
    assert "SECURITY_REMEDIATION_ROOT: /var/lib/aionex/security-remediations" in backup
    assert "security_remediation_data:/var/lib/aionex/security-remediations:ro" in backup
    assert "security_tool_cache_data" not in backup
    assert "project_npm_cache_data" not in backup
    assert "postgres_socket" not in backup


def test_fr04b10_security_remediation_settings_snapshot_and_entrypoint_are_explicit() -> None:
    settings = SETTINGS.read_text(encoding="utf-8")
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "BACKUP_SECURITY_REMEDIATIONS_ENABLED" in settings
    assert "SECURITY_REMEDIATION_ROOT" in settings
    assert '"security_remediation_data"' in snapshot
    assert "Security remediation" in snapshot
    assert "BACKUP_SECURITY_REMEDIATIONS_ENABLED" in snapshot
    assert "Unable to prepare private security remediation root" in entrypoint
    assert "Private security remediation root is not owned or permissioned correctly" in entrypoint
    assert "security_remediation_meta" in entrypoint
