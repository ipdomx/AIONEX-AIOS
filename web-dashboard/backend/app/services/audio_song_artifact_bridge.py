"""Private, short-lived artifact ingress for the RunPod open-song worker.

Tokens are action-scoped HMAC grants. They are never persisted. Artifact IDs are
opaque random identifiers and cannot encode filesystem paths or tenant data.
"""
from __future__ import annotations

import hashlib
from contextlib import suppress
import hmac
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

_ARTIFACT_ID_RE = re.compile(r"^[0-9a-f]{48}$")
_TOKEN_RE = re.compile(r"^(?P<expiry>[0-9]{10}):(?P<signature>[0-9a-f]{64})$")
_ACTIONS = frozenset({"put", "get", "delete"})
_DOMAIN = "aionex.audio-song-artifact.v1"


class AudioSongArtifactBridgeError(ValueError):
    """An artifact grant, identifier, or storage path is unsafe."""


def validate_artifact_id(value: str) -> str:
    artifact_id = str(value or "").strip()
    if not _ARTIFACT_ID_RE.fullmatch(artifact_id):
        raise AudioSongArtifactBridgeError("artifact identifier is invalid")
    return artifact_id


def validate_public_origin(value: str) -> str:
    origin = str(value or "").strip().rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.port not in {None, 443}
    ):
        raise AudioSongArtifactBridgeError("artifact bridge origin is invalid")
    return origin


def artifact_url(origin: str, artifact_id: str) -> str:
    safe_origin = validate_public_origin(origin)
    safe_id = validate_artifact_id(artifact_id)
    return f"{safe_origin}/api/v1/audio-song-artifacts/{safe_id}"


def _message(action: str, artifact_id: str, expiry: int) -> bytes:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in _ACTIONS:
        raise AudioSongArtifactBridgeError("artifact action is invalid")
    safe_id = validate_artifact_id(artifact_id)
    return f"{_DOMAIN}|{normalized_action}|{safe_id}|{int(expiry)}".encode("ascii")


def issue_artifact_token(
    action: str,
    artifact_id: str,
    *,
    secret: str,
    ttl_seconds: int,
    now_epoch: int | None = None,
) -> str:
    if len(secret) < 32:
        raise AudioSongArtifactBridgeError("artifact signing secret is invalid")
    ttl = int(ttl_seconds)
    if not 60 <= ttl <= 3_600:
        raise AudioSongArtifactBridgeError("artifact token TTL is invalid")
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    expiry = now + ttl
    signature = hmac.new(
        secret.encode("utf-8"), _message(action, artifact_id, expiry), hashlib.sha256
    ).hexdigest()
    return f"{expiry}:{signature}"


def verify_artifact_token(
    token: str,
    action: str,
    artifact_id: str,
    *,
    secret: str,
    now_epoch: int | None = None,
) -> None:
    if len(secret) < 32:
        raise AudioSongArtifactBridgeError("artifact signing secret is invalid")
    match = _TOKEN_RE.fullmatch(str(token or "").strip())
    if match is None:
        raise AudioSongArtifactBridgeError("artifact token is invalid")
    expiry = int(match.group("expiry"))
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    if expiry < now or expiry > now + 3_600:
        raise AudioSongArtifactBridgeError("artifact token is expired or out of bounds")
    expected = hmac.new(
        secret.encode("utf-8"), _message(action, artifact_id, expiry), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(match.group("signature"), expected):
        raise AudioSongArtifactBridgeError("artifact token signature is invalid")


def bearer_token(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if not value.startswith("Bearer "):
        raise AudioSongArtifactBridgeError("artifact authorization is missing")
    token = value[7:].strip()
    if not _TOKEN_RE.fullmatch(token):
        raise AudioSongArtifactBridgeError("artifact authorization is invalid")
    return token


def artifact_path(root: str | Path, artifact_id: str) -> Path:
    safe_id = validate_artifact_id(artifact_id)
    base = Path(root)
    if base.is_symlink():
        raise AudioSongArtifactBridgeError("artifact root is unsafe")
    resolved = base.resolve(strict=False)
    return resolved / f"{safe_id}.wav"


def purge_stale_artifacts(
    root: str | Path,
    *,
    max_age_seconds: int,
    now_epoch: float | None = None,
) -> int:
    max_age = int(max_age_seconds)
    if not 300 <= max_age <= 86_400:
        raise AudioSongArtifactBridgeError("artifact retention is invalid")
    base = Path(root)
    if not base.exists():
        return 0
    if not base.is_dir() or base.is_symlink():
        raise AudioSongArtifactBridgeError("artifact root is unsafe")
    now = time.time() if now_epoch is None else float(now_epoch)
    removed = 0
    for candidate in base.iterdir():
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if candidate.name.endswith(".tmp") or re.fullmatch(r"[0-9a-f]{48}\.wav", candidate.name):
            try:
                if now - candidate.stat().st_mtime > max_age:
                    candidate.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
    return removed


def ensure_artifact_root(root: str | Path) -> Path:
    base = Path(root)
    if base.exists() and (not base.is_dir() or base.is_symlink()):
        raise AudioSongArtifactBridgeError("artifact root is unsafe")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with suppress(PermissionError):
        os.chmod(base, 0o700)
    return base.resolve()
