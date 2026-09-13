from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard" / "docker-compose.production.yml"
SETTINGS = ROOT / "web-dashboard" / "backend" / "app" / "core" / "config.py"
SNAPSHOT = ROOT / "web-dashboard" / "backend" / "app" / "services" / "three_d_asset_backup.py"
ENTRYPOINT = ROOT / "web-dashboard" / "backend" / "scripts" / "docker-entrypoint.sh"


def _service_block(name: str, next_name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    return text.split(f"\n  {name}:", 1)[1].split(f"\n\n  {next_name}:", 1)[0]


def test_fr04b8_backup_worker_mounts_audio_ingress_read_only_only() -> None:
    init = _service_block("backup-asset-root-init", "backup-worker")
    backup = _service_block("backup-worker", "communication-worker")
    assert "audio_song_ingress_data:/var/lib/aionex/audio-song-provider-ingress:rw" in init
    assert 'BACKUP_AUDIO_SONG_INGRESS_ENABLED: "true"' in backup
    assert "AUDIO_SONG_ARTIFACT_BRIDGE_ROOT: /var/lib/aionex/audio-song-provider-ingress" in backup
    assert "audio_song_ingress_data:/var/lib/aionex/audio-song-provider-ingress:ro" in backup
    assert "project_npm_cache_data" not in backup


def test_fr04b8_audio_ingress_settings_snapshot_and_entrypoint_are_explicit() -> None:
    settings = SETTINGS.read_text(encoding="utf-8")
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "BACKUP_AUDIO_SONG_INGRESS_ENABLED" in settings
    assert '"audio_song_ingress_data"' in snapshot
    assert "Audio song ingress" in snapshot
    assert "BACKUP_AUDIO_SONG_INGRESS_ENABLED" in snapshot
    assert "Unable to prepare private audio song ingress root" in entrypoint
    assert "Private audio song ingress root is not owned or permissioned correctly" in entrypoint
    assert "audio_song_ingress_meta" in entrypoint
