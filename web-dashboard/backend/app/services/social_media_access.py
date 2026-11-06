"""Media for P3 publishing: composer uploads, Studio assets and provider URLs.

Media references are opaque: ``upload:<uuid>`` (a ``SocialMediaUpload`` of
the same user) or ``studio:<uuid>`` (an active image/video ``StudioAsset`` of
the same organization, the Studio's own access rule). Instagram fetches media
from a public URL, so a referenced file is exposed either through a storage
presigned URL (S3-compatible backends) or through a short-lived,
HMAC-signed bridge URL under ``SOCIAL_MEDIA_PUBLIC_BASE_URL`` that serves
exactly one verified file and nothing else, the same pattern as the Identity
Media provider-input bridge.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import SocialMediaUpload, StudioAsset
from app.services import production_studio
from app.services.media_storage import (
    LocalMediaObjectStore,
    MediaStorageError,
    media_object_store,
    media_object_store_for_backend,
)
from app.services.social_connectors import SocialConnectorError
from app.services.social_media_probe import (
    IMAGE_TYPES,
    MAX_PROBE_BYTES,
    VIDEO_TYPES,
    MediaProbeError,
    probe,
)
from app.services.social_publishing_rules import MediaInfo

REF_RE = re.compile(r"^(upload|studio):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,600}\.[0-9a-f]{64}$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
UPLOAD_IMAGE_MAX_BYTES = 10 * 1024 * 1024
UPLOAD_VIDEO_MAX_BYTES = 100 * 1024 * 1024
MAX_MEDIA_PER_POST = 10
_DOMAIN = b"aionex-social-media-url-v1"
_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
}


@dataclass(frozen=True)
class ResolvedMedia:
    ref: str
    source: str  # upload | studio
    row_id: str
    organization_id: str
    info: MediaInfo
    storage_backend: str  # local | s3 | studio-local
    storage_key: str
    sha256: str


def _signing_key(secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), _DOMAIN, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_media_token(
    ref: str, organization_id: str, *, ttl_seconds: int | None = None, now: int | None = None
) -> str:
    if not REF_RE.fullmatch(ref):
        raise SocialConnectorError("media-reference-invalid")
    secret = str(settings.SECRET_KEY or "")
    if len(secret) < 32:
        raise SocialConnectorError("media-signing-unavailable", status_code=503)
    ttl = int(ttl_seconds or settings.SOCIAL_MEDIA_URL_TTL_SECONDS)
    issued = int(time.time()) if now is None else int(now)
    body = _b64(
        json.dumps(
            {"v": 1, "ref": ref, "org": organization_id, "exp": issued + ttl},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    )
    signature = hmac.new(_signing_key(secret), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_media_token(token: str, *, now: int | None = None) -> tuple[str, str]:
    """Return (ref, organization_id) for a valid, unexpired token."""

    if not TOKEN_RE.fullmatch(token or ""):
        raise SocialConnectorError("media-token-invalid", status_code=404)
    body, supplied = token.split(".", 1)
    candidates = [str(settings.SECRET_KEY or ""), str(settings.SECRET_KEY_PREVIOUS or "")]
    valid = False
    for secret in candidates:
        if len(secret) < 32:
            continue
        expected = hmac.new(_signing_key(secret), body.encode("ascii"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, supplied):
            valid = True
            break
    if not valid:
        raise SocialConnectorError("media-token-invalid", status_code=404)
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SocialConnectorError("media-token-invalid", status_code=404) from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise SocialConnectorError("media-token-invalid", status_code=404)
    current = int(time.time()) if now is None else int(now)
    if not isinstance(payload.get("exp"), int) or payload["exp"] < current:
        raise SocialConnectorError("media-token-expired", status_code=404)
    ref, org = str(payload.get("ref") or ""), str(payload.get("org") or "")
    if not REF_RE.fullmatch(ref) or not org:
        raise SocialConnectorError("media-token-invalid", status_code=404)
    return ref, org


def public_filename(media: ResolvedMedia) -> str:
    extension = _EXTENSIONS.get(media.info.media_type, "bin")
    return f"{media.row_id}.{extension}"


def public_url(media: ResolvedMedia) -> str:
    """A URL Meta can fetch for this media, valid for SOCIAL_MEDIA_URL_TTL_SECONDS."""

    if media.storage_backend not in {"local", "studio-local"}:
        try:
            store = media_object_store_for_backend(media.storage_backend)
            url = store.presigned_get(
                media.storage_key,
                filename=public_filename(media),
                content_type=media.info.media_type,
                expires_seconds=min(int(settings.SOCIAL_MEDIA_URL_TTL_SECONDS), 3600),
                inline=True,
            )
        except MediaStorageError as exc:
            raise SocialConnectorError("media-url-unavailable", status_code=503) from exc
        if url:
            return url
    base = str(settings.SOCIAL_MEDIA_PUBLIC_BASE_URL or "").rstrip("/")
    if not base.startswith("https://"):
        raise SocialConnectorError("media-public-base-url-invalid", status_code=503)
    token = sign_media_token(media.ref, media.organization_id)
    return f"{base}/api/v1/social/media/public/{token}/{public_filename(media)}"


# --- resolution ------------------------------------------------------------------------


def _studio_storage(asset: StudioAsset) -> tuple[str, str]:
    output = dict(asset.asset_metadata or {}).get("media_graph_output")
    if isinstance(output, dict):
        backend = str(output.get("storage_backend") or "").strip().lower()
        key = str(output.get("storage_key") or asset.storage_path).strip()
        if backend and key:
            return backend, key
    return "studio-local", asset.storage_path


def _studio_head(asset: StudioAsset, backend: str, key: str) -> bytes | None:
    try:
        if backend == "studio-local":
            path = Path(key).resolve()
            if production_studio.protected_root() not in path.parents or not path.is_file():
                return None
            with path.open("rb") as handle:
                return handle.read(MAX_PROBE_BYTES)
        if int(asset.size_bytes) > MAX_PROBE_BYTES:
            return None
        return media_object_store_for_backend(backend).get_bytes(key, max_bytes=MAX_PROBE_BYTES)
    except (OSError, MediaStorageError):
        return None


def _studio_info(ref: str, asset: StudioAsset, backend: str, key: str) -> MediaInfo:
    media_type = str(asset.media_type or "").split(";")[0].strip().lower()
    kind = "video" if media_type.startswith("video/") else "image"
    width = height = duration = None
    head = _studio_head(asset, backend, key)
    if head:
        try:
            probed = probe(head)
        except MediaProbeError:
            probed = None
        if probed is not None:
            media_type, kind = probed.media_type, probed.kind
            width, height, duration = probed.width, probed.height, probed.duration_ms
    return MediaInfo(
        ref=ref,
        kind=kind,
        media_type=media_type,
        size_bytes=int(asset.size_bytes),
        width=width,
        height=height,
        duration_ms=duration,
        filename=str(asset.filename or "")[:200],
    )


async def resolve_media(
    session: AsyncSession, *, organization_id: str, user_id: str, refs: list[str]
) -> list[ResolvedMedia]:
    if len(refs) > MAX_MEDIA_PER_POST:
        raise SocialConnectorError("too-many-media-items", status_code=422)
    resolved: list[ResolvedMedia] = []
    for ref in refs:
        match = REF_RE.fullmatch(str(ref or ""))
        if match is None:
            raise SocialConnectorError("media-reference-invalid", status_code=422)
        source, row_id = match.group(1), match.group(2)
        if source == "upload":
            upload = await session.scalar(
                select(SocialMediaUpload).where(
                    SocialMediaUpload.id == row_id,
                    SocialMediaUpload.organization_id == organization_id,
                    SocialMediaUpload.user_id == user_id,
                    SocialMediaUpload.status == "ready",
                )
            )
            if upload is None:
                raise SocialConnectorError("media-not-found", status_code=422)
            resolved.append(
                ResolvedMedia(
                    ref=ref,
                    source="upload",
                    row_id=upload.id,
                    organization_id=organization_id,
                    info=MediaInfo(
                        ref=ref,
                        kind=upload.kind,
                        media_type=upload.media_type,
                        size_bytes=int(upload.size_bytes),
                        width=upload.width,
                        height=upload.height,
                        duration_ms=upload.duration_ms,
                        filename=upload.filename,
                    ),
                    storage_backend=upload.storage_backend,
                    storage_key=upload.storage_key,
                    sha256=upload.sha256,
                )
            )
            continue
        asset = await session.scalar(
            select(StudioAsset).where(
                StudioAsset.id == row_id,
                StudioAsset.organization_id == organization_id,
                StudioAsset.created_by_id == user_id,
                StudioAsset.status == "active",
            )
        )
        media_type = str(asset.media_type if asset else "").split(";")[0].strip().lower()
        if asset is None or media_type not in {*IMAGE_TYPES, *VIDEO_TYPES}:
            raise SocialConnectorError("media-not-found", status_code=422)
        backend, key = _studio_storage(asset)
        resolved.append(
            ResolvedMedia(
                ref=ref,
                source="studio",
                row_id=asset.id,
                organization_id=organization_id,
                info=_studio_info(ref, asset, backend, key),
                storage_backend=backend,
                storage_key=key,
                sha256=asset.checksum,
            )
        )
    return resolved


async def bridge_file(session: AsyncSession, token: str, filename: str) -> tuple[Path, str]:
    """Verify a bridge token and return the verified local file and its type."""

    if not FILENAME_RE.fullmatch(filename or ""):
        raise SocialConnectorError("media-not-found", status_code=404)
    ref, organization_id = verify_media_token(token)
    match = REF_RE.fullmatch(ref)
    if match is None:
        raise SocialConnectorError("media-not-found", status_code=404)
    source, row_id = match.group(1), match.group(2)
    if source == "upload":
        upload = await session.scalar(
            select(SocialMediaUpload).where(
                SocialMediaUpload.id == row_id,
                SocialMediaUpload.organization_id == organization_id,
                SocialMediaUpload.status == "ready",
            )
        )
        if upload is None or upload.storage_backend != "local":
            raise SocialConnectorError("media-not-found", status_code=404)
        if filename != f"{upload.id}.{_EXTENSIONS.get(upload.media_type, 'bin')}":
            raise SocialConnectorError("media-not-found", status_code=404)
        try:
            store = LocalMediaObjectStore()
            path = store.verified_path(
                upload.storage_key, checksum=upload.sha256, size_bytes=int(upload.size_bytes)
            )
        except MediaStorageError as exc:
            raise SocialConnectorError("media-not-found", status_code=404) from exc
        return path, upload.media_type
    asset = await session.scalar(
        select(StudioAsset).where(
            StudioAsset.id == row_id,
            StudioAsset.organization_id == organization_id,
            StudioAsset.status == "active",
        )
    )
    if asset is None:
        raise SocialConnectorError("media-not-found", status_code=404)
    backend, key = _studio_storage(asset)
    media_type = str(asset.media_type or "").split(";")[0].strip().lower()
    if filename != f"{asset.id}.{_EXTENSIONS.get(media_type, 'bin')}":
        raise SocialConnectorError("media-not-found", status_code=404)
    try:
        if backend == "studio-local":
            path = production_studio.verify_artifact(key, asset.checksum, int(asset.size_bytes))
        elif backend == "local":
            path = LocalMediaObjectStore().verified_path(
                key, checksum=asset.checksum, size_bytes=int(asset.size_bytes)
            )
        else:
            raise SocialConnectorError("media-not-found", status_code=404)
    except (FileNotFoundError, ValueError, MediaStorageError) as exc:
        raise SocialConnectorError("media-not-found", status_code=404) from exc
    return path, media_type


# --- uploads ---------------------------------------------------------------------------


def public_upload(row: SocialMediaUpload) -> dict[str, Any]:
    return {
        "ref": f"upload:{row.id}",
        "id": row.id,
        "source": "upload",
        "kind": row.kind,
        "filename": row.filename,
        "media_type": row.media_type,
        "size_bytes": int(row.size_bytes),
        "width": row.width,
        "height": row.height,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at,
    }


def public_studio_asset(asset: StudioAsset) -> dict[str, Any]:
    media_type = str(asset.media_type or "").split(";")[0].strip().lower()
    return {
        "ref": f"studio:{asset.id}",
        "id": asset.id,
        "source": "studio",
        "kind": "video" if media_type.startswith("video/") else "image",
        "filename": str(asset.filename or "")[:200],
        "title": asset.title,
        "media_type": media_type,
        "size_bytes": int(asset.size_bytes),
        "width": None,
        "height": None,
        "duration_ms": None,
        "created_at": asset.created_at,
    }


def _safe_filename(value: str | None, media_type: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(str(value or "media")).stem).strip("-._")
    return f"{(stem or 'media')[:80]}.{_EXTENSIONS.get(media_type, 'bin')}"


def store_upload(
    *, organization_id: str, user_id: str, body: bytes, filename: str | None, declared_type: str | None
) -> SocialMediaUpload:
    """Probe, size-check and store the bytes; the caller adds and commits the row."""

    if not body:
        raise SocialConnectorError("media-empty", status_code=422)
    try:
        probed = probe(body, declared_type=declared_type)
    except MediaProbeError as exc:
        raise SocialConnectorError("media-type-unsupported", status_code=415) from exc
    limit = UPLOAD_VIDEO_MAX_BYTES if probed.kind == "video" else UPLOAD_IMAGE_MAX_BYTES
    if len(body) > limit:
        raise SocialConnectorError("media-too-large", status_code=413)
    upload_id = str(uuid4())
    extension = _EXTENSIONS[probed.media_type]
    key = f"social-media/{organization_id}/{user_id}/{upload_id}.{extension}"
    try:
        store = media_object_store()
        stored = store.put_bytes(key, body, probed.media_type, metadata={"purpose": "social-post"})
    except MediaStorageError as exc:
        raise SocialConnectorError("media-storage-unavailable", status_code=503) from exc
    return SocialMediaUpload(
        id=upload_id,
        organization_id=organization_id,
        user_id=user_id,
        kind=probed.kind,
        filename=_safe_filename(filename, probed.media_type),
        media_type=probed.media_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        width=probed.width,
        height=probed.height,
        duration_ms=probed.duration_ms,
        storage_backend=stored.backend,
        storage_key=key,
        status="ready",
    )
