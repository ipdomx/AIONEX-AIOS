from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (
    REPO_ROOT / "web-dashboard" / "docker-compose.production.yml",
    REPO_ROOT / "deploy" / "production" / "docker-compose.production.yml",
)


def _service_block(text: str, service: str, next_service: str) -> str:
    return text.split(f"  {service}:\n", 1)[1].split(f"  {next_service}:\n", 1)[0]


def test_backend_shares_private_local_media_volume_with_media_workers() -> None:
    for compose in COMPOSE_FILES:
        text = compose.read_text(encoding="utf-8")
        backend = _service_block(text, "backend", "postgres-credential-reconciler")
        assert "MEDIA_STORAGE_TYPE: local" in backend
        assert "MEDIA_STORAGE_ROOT: /var/lib/aionex/media-assets" in backend
        assert "media_asset_data:/var/lib/aionex/media-assets:rw" in backend


def test_media_workers_use_the_same_private_local_media_root() -> None:
    pairs = (
        ("media-worker", "audio-speech-worker"),
        ("audio-speech-worker", "audio-transcript-worker"),
        ("audio-transcript-worker", "audio-dubbing-worker"),
        ("audio-dubbing-worker", "audio-music-worker"),
        ("audio-music-worker", "audio-song-worker"),
        ("video-provider-worker", "design-image-worker"),
        ("design-image-worker", "design-image-derivative-worker"),
        ("design-image-derivative-worker", "three-d-worker"),
    )
    for compose in COMPOSE_FILES:
        text = compose.read_text(encoding="utf-8")
        for service, next_service in pairs:
            block = _service_block(text, service, next_service)
            assert "MEDIA_STORAGE_TYPE: local" in block
            assert "media_asset_data:/var/lib/aionex/media-assets:rw" in block
