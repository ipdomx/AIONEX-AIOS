from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (
    REPO_ROOT / "web-dashboard" / "docker-compose.production.yml",
    REPO_ROOT / "deploy" / "production" / "docker-compose.production.yml",
)


def _block(text: str, service: str, next_service: str) -> str:
    return text.split(f"  {service}:\n", 1)[1].split(f"  {next_service}:\n", 1)[0]


def test_accepted_pre_xr_media_workers_are_persistently_armed() -> None:
    expected = (
        ("audio-speech-worker", "audio-transcript-worker", 'AUDIO_SPEECH_LIVE_ENABLED: "true"'),
        ("audio-transcript-worker", "audio-dubbing-worker", 'AUDIO_TRANSCRIPT_LIVE_ENABLED: "true"'),
        ("audio-dubbing-worker", "audio-music-worker", 'AUDIO_DUBBING_LIVE_ENABLED: "true"'),
        ("audio-music-worker", "audio-song-worker", 'AUDIO_MUSIC_LIVE_ENABLED: "true"'),
        ("audio-song-worker", "audio-song-worker-secondary", 'AUDIO_SONG_LIVE_ENABLED: "true"'),
        ("video-provider-worker", "design-image-worker", 'VIDEO_EXECUTION_LIVE_ENABLED: "true"'),
        ("design-image-worker", "design-image-derivative-worker", 'DESIGN_IMAGE_LIVE_ENABLED: "true"'),
        ("design-image-derivative-worker", "three-d-worker", 'DESIGN_IMAGE_DERIVATIVE_ENABLED: "true"'),
    )
    for compose in COMPOSE_FILES:
        text = compose.read_text(encoding="utf-8")
        for service, next_service, flag in expected:
            assert flag in _block(text, service, next_service)


def test_unconfigured_secondary_open_song_route_remains_fail_closed() -> None:
    for compose in COMPOSE_FILES:
        text = compose.read_text(encoding="utf-8")
        secondary = _block(text, "audio-song-worker-secondary", "video-provider-worker")
        assert 'AUDIO_SONG_LIVE_ENABLED: "false"' in secondary
