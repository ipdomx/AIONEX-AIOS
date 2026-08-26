from __future__ import annotations

import hashlib
import io
from pathlib import Path
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import audio_song_artifacts
from app.core.config import settings
from app.services.audio_song_artifact_bridge import issue_artifact_token

SECRET = "phase36g-artifact-api-test-secret-that-is-long-enough"
ARTIFACT_ID = "d" * 48


def _wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(48_000)
        writer.writeframes(b"\x00\x00\x00\x00" * 48_000)
    return buffer.getvalue()


def _token(action: str) -> str:
    return issue_artifact_token(
        action,
        ARTIFACT_ID,
        secret=SECRET,
        ttl_seconds=600,
    )


def test_bridge_api_is_write_once_hash_checked_and_cleanup_capable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "AUDIO_SONG_ARTIFACT_BRIDGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "AUDIO_SONG_ARTIFACT_BRIDGE_MAX_BYTES", 4 * 1024 * 1024)
    monkeypatch.setattr(settings, "AUDIO_SONG_ARTIFACT_RETENTION_SECONDS", 3_600)
    app = FastAPI()
    app.include_router(audio_song_artifacts.router, prefix="/api/v1/audio-song-artifacts")
    client = TestClient(app)
    body = _wav()
    digest = hashlib.sha256(body).hexdigest()
    headers = {
        "Authorization": f"Bearer {_token('put')}",
        "Content-Type": "audio/wav",
        "X-AIONEX-Artifact-SHA256": digest,
        "X-AIONEX-Artifact-Size": str(len(body)),
    }
    response = client.put(f"/api/v1/audio-song-artifacts/{ARTIFACT_ID}", content=body, headers=headers)
    assert response.status_code == 201
    assert response.json()["sha256"] == digest
    assert client.put(f"/api/v1/audio-song-artifacts/{ARTIFACT_ID}", content=body, headers=headers).status_code == 409

    download = client.get(
        f"/api/v1/audio-song-artifacts/{ARTIFACT_ID}",
        headers={"Authorization": f"Bearer {_token('get')}"},
    )
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == digest
    assert download.headers["cache-control"].startswith("private, no-store")

    wrong_action = client.get(
        f"/api/v1/audio-song-artifacts/{ARTIFACT_ID}",
        headers={"Authorization": f"Bearer {_token('put')}"},
    )
    assert wrong_action.status_code == 404

    deleted = client.delete(
        f"/api/v1/audio-song-artifacts/{ARTIFACT_ID}",
        headers={"Authorization": f"Bearer {_token('delete')}"},
    )
    assert deleted.status_code == 204
    assert not (tmp_path / f"{ARTIFACT_ID}.wav").exists()
