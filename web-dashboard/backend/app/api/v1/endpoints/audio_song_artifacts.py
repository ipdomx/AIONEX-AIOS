"""Token-authenticated ingress for ephemeral RunPod open-song WAV artifacts."""
from __future__ import annotations

import hashlib
from contextlib import suppress
import os
from pathlib import Path
import secrets
import wave

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from app.core.config import settings
from app.services.audio_song_artifact_bridge import (
    AudioSongArtifactBridgeError,
    artifact_path,
    bearer_token,
    ensure_artifact_root,
    purge_stale_artifacts,
    verify_artifact_token,
)

router = APIRouter()
_SHA_HEADER = "x-aionex-artifact-sha256"
_SIZE_HEADER = "x-aionex-artifact-size"


def _authorize(authorization: str | None, action: str, artifact_id: str) -> None:
    try:
        token = bearer_token(authorization)
        verify_artifact_token(
            token,
            action,
            artifact_id,
            secret=settings.SECRET_KEY,
        )
    except AudioSongArtifactBridgeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


def _root() -> Path:
    try:
        root = ensure_artifact_root(settings.AUDIO_SONG_ARTIFACT_BRIDGE_ROOT)
        purge_stale_artifacts(
            root,
            max_age_seconds=settings.AUDIO_SONG_ARTIFACT_RETENTION_SECONDS,
        )
        return root
    except AudioSongArtifactBridgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Artifact ingress unavailable",
        ) from exc


def _validate_wav(path: Path) -> None:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            sample_width = source.getsampwidth()
            frame_count = source.getnframes()
            compression = source.getcomptype()
    except (wave.Error, EOFError, OSError) as exc:
        raise HTTPException(status_code=422, detail="Invalid WAV artifact") from exc
    duration = frame_count / float(sample_rate or 1)
    if (
        channels != 2
        or sample_rate != 48_000
        or sample_width != 2
        or compression != "NONE"
        or not 0.0 < duration <= 190.0
    ):
        raise HTTPException(status_code=422, detail="Invalid WAV artifact")


@router.put("/{artifact_id}", status_code=status.HTTP_201_CREATED)
async def upload_audio_song_artifact(
    artifact_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize(authorization, "put", artifact_id)
    root = _root()
    try:
        final_path = artifact_path(root, artifact_id, secret=settings.SECRET_KEY)
    except AudioSongArtifactBridgeError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    if final_path.exists():
        raise HTTPException(status_code=409, detail="Artifact already exists")

    declared_sha = str(request.headers.get(_SHA_HEADER) or "").strip().lower()
    declared_size_raw = str(request.headers.get(_SIZE_HEADER) or "").strip()
    if len(declared_sha) != 64 or any(ch not in "0123456789abcdef" for ch in declared_sha):
        raise HTTPException(status_code=400, detail="Invalid artifact evidence")
    try:
        declared_size = int(declared_size_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact evidence") from exc
    max_bytes = int(settings.AUDIO_SONG_ARTIFACT_BRIDGE_MAX_BYTES)
    if not 1 <= declared_size <= max_bytes:
        raise HTTPException(status_code=413, detail="Artifact is too large")
    content_length = request.headers.get("content-length")
    if content_length is None:
        raise HTTPException(status_code=411, detail="Content-Length required")
    try:
        if int(content_length) != declared_size:
            raise HTTPException(status_code=400, detail="Artifact size mismatch")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type not in {"audio/wav", "audio/x-wav", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Unsupported media type")

    temporary = root / f".{final_path.stem}.{secrets.token_hex(8)}.tmp"
    total = 0
    digest = hashlib.sha256()
    try:
        with open(temporary, "xb") as destination:
            os.chmod(temporary, 0o600)
            async for chunk in request.stream():
                total += len(chunk)
                if total > declared_size or total > max_bytes:
                    raise HTTPException(status_code=413, detail="Artifact is too large")
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if total != declared_size or digest.hexdigest() != declared_sha:
            raise HTTPException(status_code=422, detail="Artifact evidence mismatch")
        _validate_wav(temporary)
        try:
            os.link(temporary, final_path)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="Artifact already exists") from exc
        return {
            "stored": True,
            "artifact_id": artifact_id,
            "sha256": declared_sha,
            "size_bytes": declared_size,
        }
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


@router.get("/{artifact_id}")
async def download_audio_song_artifact(
    artifact_id: str,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization, "get", artifact_id)
    root = _root()
    try:
        path = artifact_path(root, artifact_id, secret=settings.SECRET_KEY)
    except AudioSongArtifactBridgeError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    if not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "attachment; filename=artifact.wav",
        },
    )


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_audio_song_artifact(
    artifact_id: str,
    authorization: str | None = Header(default=None),
) -> Response:
    _authorize(authorization, "delete", artifact_id)
    root = _root()
    try:
        path = artifact_path(root, artifact_id, secret=settings.SECRET_KEY)
    except AudioSongArtifactBridgeError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    if path.is_symlink():
        raise HTTPException(status_code=404, detail="Not found")
    with suppress(FileNotFoundError):
        path.unlink()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
