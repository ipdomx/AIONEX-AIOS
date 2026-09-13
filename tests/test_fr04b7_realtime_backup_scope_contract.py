from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SETTINGS = ROOT / "web-dashboard" / "backend" / "app" / "core" / "config.py"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"


def _service_block(name: str, next_name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"\n  {name}:", 1)[1].split(f"\n\n  {next_name}:", 1)[0]


def test_fr04b7_backup_worker_mounts_realtime_recordings_read_only_only() -> None:
    init = _service_block("backup-asset-root-init", "backup-worker")
    backup = _service_block("backup-worker", "communication-worker")
    assert "realtime_recording_data:/var/lib/aionex/realtime-recordings:rw" in init
    assert "install -d -m 0770 -o 1001 -g 1000" in init
    assert "chmod 2770" in init
    assert "FSETID" in init
    assert 'BACKUP_REALTIME_RECORDINGS_ENABLED: "true"' in backup
    assert "REALTIME_RECORDING_ROOT: /var/lib/aionex/realtime-recordings" in backup
    assert "realtime_recording_data:/var/lib/aionex/realtime-recordings:ro" in backup
    assert "project_npm_cache_data" not in backup
    assert "security_remediation_data" not in backup


def test_fr04b7_realtime_settings_snapshot_and_egress_mode_are_explicit() -> None:
    settings = SETTINGS.read_text(encoding="utf-8")
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "BACKUP_REALTIME_RECORDINGS_ENABLED" in settings
    assert '"realtime_recording_data"' in snapshot
    assert "Realtime recording" in snapshot
    assert "BACKUP_REALTIME_RECORDINGS_ENABLED" in snapshot
    assert "directory_mode=0o2770" in snapshot
    assert "file_mode=0o660" in snapshot
    assert "BACKUP_REALTIME_RECORDING_OWNER_UID" in settings
    assert "BACKUP_REALTIME_RECORDING_GROUP_GID" in settings
    assert "BACKUP_REALTIME_RECORDING_OWNER_UID" in snapshot
    assert "BACKUP_REALTIME_RECORDING_GROUP_GID" in snapshot
    assert 'command: ["chown 1001:1000 /recordings && chmod 2770 /recordings"]' in compose
