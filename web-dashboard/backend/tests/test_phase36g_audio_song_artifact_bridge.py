from __future__ import annotations

from pathlib import Path

import pytest

from app.services.audio_song_artifact_bridge import (
    AudioSongArtifactBridgeError,
    artifact_path,
    artifact_url,
    bearer_token,
    issue_artifact_token,
    purge_stale_artifacts,
    verify_artifact_token,
)

SECRET = "phase36g-artifact-bridge-test-secret-that-is-long-enough"
ARTIFACT_ID = "a" * 48


def test_tokens_are_action_scoped_expiring_and_not_path_bearing() -> None:
    token = issue_artifact_token(
        "put", ARTIFACT_ID, secret=SECRET, ttl_seconds=600, now_epoch=1_800_000_000
    )
    verify_artifact_token(
        token, "put", ARTIFACT_ID, secret=SECRET, now_epoch=1_800_000_500
    )
    with pytest.raises(AudioSongArtifactBridgeError):
        verify_artifact_token(
            token, "get", ARTIFACT_ID, secret=SECRET, now_epoch=1_800_000_500
        )
    with pytest.raises(AudioSongArtifactBridgeError):
        verify_artifact_token(
            token, "put", ARTIFACT_ID, secret=SECRET, now_epoch=1_800_000_601
        )
    assert ARTIFACT_ID not in token
    assert bearer_token(f"Bearer {token}") == token


def test_public_url_and_storage_path_are_strict() -> None:
    assert artifact_url("https://api.vip-e.net", ARTIFACT_ID).endswith(ARTIFACT_ID)
    assert artifact_path("/tmp/aionex-bridge", ARTIFACT_ID).name == f"{ARTIFACT_ID}.wav"
    for unsafe in ("../escape", "A" * 48, "a" * 47, "a" * 49):
        with pytest.raises(AudioSongArtifactBridgeError):
            artifact_path("/tmp/aionex-bridge", unsafe)
    with pytest.raises(AudioSongArtifactBridgeError):
        artifact_url("http://api.vip-e.net", ARTIFACT_ID)


def test_stale_purge_only_removes_bridge_artifacts(tmp_path: Path) -> None:
    old = tmp_path / f"{'b' * 48}.wav"
    keep = tmp_path / f"{'c' * 48}.wav"
    unrelated = tmp_path / "keep.txt"
    old.write_bytes(b"old")
    keep.write_bytes(b"new")
    unrelated.write_bytes(b"x")
    old.touch()
    keep.touch()
    import os

    os.utime(old, (100.0, 100.0))
    os.utime(keep, (9_900.0, 9_900.0))
    removed = purge_stale_artifacts(tmp_path, max_age_seconds=600, now_epoch=10_000.0)
    assert removed == 1
    assert not old.exists()
    assert keep.exists()
    assert unrelated.exists()
