"""Private local/S3 object storage for user 3D inputs and generated artifacts."""

from __future__ import annotations

import base64
import binascii
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import stat
import time
from typing import Final
from urllib.parse import quote, urlsplit
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.core.config import settings

GLB_MEDIA_TYPE: Final = "model/gltf-binary"
_LOCAL_TOKEN_DOMAIN: Final = "aionex.three-d-local-artifact.v1"


class ThreeDStorageError(RuntimeError):
    """Sanitized 3D storage failure."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str
    content_type: str


@dataclass(frozen=True, slots=True)
class LocalArtifactGrant:
    project_id: str
    job_id: str
    artifact_id: str
    inline: bool
    expires_at_epoch: int


def _grant_payload(grant: LocalArtifactGrant) -> bytes:
    return json.dumps(
        {
            "artifact_id": grant.artifact_id,
            "exp": int(grant.expires_at_epoch),
            "inline": bool(grant.inline),
            "job_id": grant.job_id,
            "project_id": grant.project_id,
            "v": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise ThreeDStorageError("3D artifact token is invalid") from exc


def issue_local_artifact_token(
    *,
    project_id: str,
    job_id: str,
    artifact_id: str,
    inline: bool,
    secret: str,
    ttl_seconds: int,
    now_epoch: int | None = None,
) -> str:
    if len(str(secret or "")) < 32:
        raise ThreeDStorageError("3D artifact signing secret is invalid")
    ttl = int(ttl_seconds)
    if not 60 <= ttl <= 3600:
        raise ThreeDStorageError("3D artifact token TTL is invalid")
    for label, value in (
        ("project", project_id),
        ("job", job_id),
        ("artifact", artifact_id),
    ):
        text = str(value or "").strip()
        if not text or len(text) > 80 or any(char not in "0123456789abcdefABCDEF-" for char in text):
            raise ThreeDStorageError(f"3D {label} identifier is invalid")
    current = int(time.time()) if now_epoch is None else int(now_epoch)
    grant = LocalArtifactGrant(
        project_id=project_id,
        job_id=job_id,
        artifact_id=artifact_id,
        inline=bool(inline),
        expires_at_epoch=current + ttl,
    )
    encoded = _b64url(_grant_payload(grant))
    signature = hmac.new(
        str(secret).encode("utf-8"),
        f"{_LOCAL_TOKEN_DOMAIN}|{encoded}".encode("ascii"),
        "sha256",
    ).hexdigest()
    return f"{encoded}.{signature}"


def verify_local_artifact_token(
    token: str,
    *,
    secret: str,
    now_epoch: int | None = None,
) -> LocalArtifactGrant:
    if len(str(secret or "")) < 32:
        raise ThreeDStorageError("3D artifact signing secret is invalid")
    text = str(token or "").strip()
    if len(text) > 2048 or text.count(".") != 1:
        raise ThreeDStorageError("3D artifact token is invalid")
    encoded, supplied = text.split(".", 1)
    if len(supplied) != 64:
        raise ThreeDStorageError("3D artifact token is invalid")
    expected = hmac.new(
        str(secret).encode("utf-8"),
        f"{_LOCAL_TOKEN_DOMAIN}|{encoded}".encode("ascii"),
        "sha256",
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ThreeDStorageError("3D artifact token signature is invalid")
    try:
        payload = json.loads(_b64url_decode(encoded))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise ThreeDStorageError("3D artifact token payload is invalid") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ThreeDStorageError("3D artifact token payload is invalid")
    try:
        expiry = int(payload["exp"])
        inline = payload["inline"]
        if not isinstance(inline, bool):
            raise TypeError
        grant = LocalArtifactGrant(
            project_id=str(payload["project_id"]),
            job_id=str(payload["job_id"]),
            artifact_id=str(payload["artifact_id"]),
            inline=inline,
            expires_at_epoch=expiry,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ThreeDStorageError("3D artifact token payload is invalid") from exc
    current = int(time.time()) if now_epoch is None else int(now_epoch)
    if expiry < current or expiry > current + 3600:
        raise ThreeDStorageError("3D artifact token is expired or out of bounds")
    # Reuse issuance validation for identifiers without changing the signed expiry.
    for label, value in (
        ("project", grant.project_id),
        ("job", grant.job_id),
        ("artifact", grant.artifact_id),
    ):
        if not value or len(value) > 80 or any(char not in "0123456789abcdefABCDEF-" for char in value):
            raise ThreeDStorageError(f"3D {label} identifier is invalid")
    return grant


def local_artifact_url(origin: str, token: str) -> str:
    value = str(origin or "").strip().rstrip("/")
    parsed = urlsplit(value)
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
        raise ThreeDStorageError("3D artifact public origin is invalid")
    return f"{value}/api/v1/projects/3d/artifacts/local?token={quote(token, safe='')}"


class ThreeDObjectStore:
    def __init__(self) -> None:
        storage_type = settings.THREE_D_STORAGE_TYPE.strip().lower()
        if storage_type == "inherit":
            storage_type = settings.STORAGE_TYPE.strip().lower()
        self.backend = storage_type
        self.root: Path | None = None
        self.bucket: str | None = None
        self.region: str | None = None
        self.client = None
        if storage_type == "local":
            self._init_local()
            return
        if storage_type != "s3":
            raise ThreeDStorageError("3D object storage is not configured")
        required = {
            "AWS_ACCESS_KEY_ID": settings.AWS_ACCESS_KEY_ID,
            "AWS_SECRET_ACCESS_KEY": settings.AWS_SECRET_ACCESS_KEY,
            "AWS_S3_BUCKET": settings.AWS_S3_BUCKET,
            "AWS_S3_REGION": settings.AWS_S3_REGION,
        }
        if any(not str(value or "").strip() for value in required.values()):
            raise ThreeDStorageError("3D object storage is not configured")
        self.bucket = str(settings.AWS_S3_BUCKET).strip()
        self.region = str(settings.AWS_S3_REGION).strip()
        self.client = boto3.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=str(settings.AWS_ACCESS_KEY_ID),
            aws_secret_access_key=str(settings.AWS_SECRET_ACCESS_KEY),
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    @property
    def is_local(self) -> bool:
        return self.backend == "local"

    def _init_local(self) -> None:
        source = Path(settings.THREE_D_STORAGE_ROOT)
        if source.exists():
            metadata = source.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ThreeDStorageError("3D local storage root is unsafe")
        else:
            try:
                source.mkdir(parents=True, mode=0o700)
                os.chmod(source, 0o700)
            except OSError as exc:
                raise ThreeDStorageError("3D local storage root is unavailable") from exc
        root = source.resolve(strict=True)
        mode = stat.S_IMODE(root.stat().st_mode)
        if mode & 0o077:
            raise ThreeDStorageError("3D local storage root permissions are unsafe")
        if not os.access(root, os.R_OK | os.X_OK):
            raise ThreeDStorageError("3D local storage root is unreadable")
        self.root = root

    def _local_path(self, key: str) -> Path:
        if not self.is_local or self.root is None:
            raise ThreeDStorageError("3D local storage is not active")
        normalized = str(key or "").strip().lstrip("/")
        relative = Path(normalized)
        if not normalized or relative.is_absolute() or ".." in relative.parts:
            raise ThreeDStorageError("3D object key is invalid")
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                metadata = current.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise ThreeDStorageError("3D object path contains a symlink")
        return self.root.joinpath(*relative.parts)

    def _ensure_local_parent(self, destination: Path) -> None:
        if not self.is_local or self.root is None:
            raise ThreeDStorageError("3D local storage is not active")
        try:
            relative = destination.parent.relative_to(self.root)
        except ValueError as exc:
            raise ThreeDStorageError("3D object key escapes the private root") from exc
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                metadata = current.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise ThreeDStorageError("3D object parent path is unsafe")
            else:
                current.mkdir(mode=0o700)
            os.chmod(current, 0o700)

    @staticmethod
    def input_key(
        organization_id: str, project_id: str, job_id: str, suffix: str
    ) -> str:
        normalized = suffix.lower().strip(".") or "img"
        return f"3d/{organization_id}/{project_id}/{job_id}/input.{normalized}"

    @staticmethod
    def output_key(organization_id: str, project_id: str, job_id: str) -> str:
        return f"3d/{organization_id}/{project_id}/{job_id}/final.glb"

    def put_bytes(
        self,
        key: str,
        body: bytes,
        content_type: str,
        *,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        digest = sha256(body).hexdigest()
        if self.is_local:
            destination = self._local_path(key)
            temporary: Path | None = None
            try:
                self._ensure_local_parent(destination)
                temporary = destination.with_name(
                    f".{destination.name}.{uuid4().hex}.partial"
                )
                with temporary.open("xb") as stream:
                    os.chmod(temporary, 0o600)
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
                os.chmod(destination, 0o600)
            except OSError as exc:
                if temporary is not None:
                    with suppress(OSError):
                        temporary.unlink(missing_ok=True)
                raise ThreeDStorageError("3D object upload failed: OSError") from exc
            return StoredObject(
                key=key,
                size_bytes=len(body),
                sha256=digest,
                content_type=content_type,
            )
        try:
            assert self.client is not None and self.bucket is not None
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                ServerSideEncryption="AES256",
                Metadata={"sha256": digest, **(metadata or {})},
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ThreeDStorageError(
                f"3D object upload failed: {type(exc).__name__}"
            ) from None
        return StoredObject(
            key=key, size_bytes=len(body), sha256=digest, content_type=content_type
        )

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
        limit = max(1, int(max_bytes))
        if self.is_local:
            path = self._local_path(key)
            try:
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise ThreeDStorageError("3D object is unavailable")
                if metadata.st_size <= 0 or metadata.st_size > limit:
                    raise ThreeDStorageError("3D object size is outside the allowed range")
                body = path.read_bytes()
            except FileNotFoundError as exc:
                raise ThreeDStorageError("3D object is unavailable") from exc
            except OSError as exc:
                raise ThreeDStorageError("3D object download failed: OSError") from exc
            if len(body) != metadata.st_size or len(body) > limit:
                raise ThreeDStorageError("3D object changed during read")
            return body
        try:
            assert self.client is not None and self.bucket is not None
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            declared = int(response.get("ContentLength") or 0)
            if declared <= 0 or declared > limit:
                raise ThreeDStorageError("3D object size is outside the allowed range")
            body = response["Body"].read(limit + 1)
        except ThreeDStorageError:
            raise
        except (BotoCoreError, ClientError, OSError, KeyError) as exc:
            raise ThreeDStorageError(
                f"3D object download failed: {type(exc).__name__}"
            ) from None
        if len(body) > limit:
            raise ThreeDStorageError("3D object exceeds the allowed size")
        return body

    def verified_local_path(
        self, key: str, *, checksum: str, size_bytes: int
    ) -> Path:
        if not self.is_local:
            raise ThreeDStorageError("3D local storage is not active")
        expected = str(checksum or "").strip().lower()
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise ThreeDStorageError("3D artifact checksum is invalid")
        path = self._local_path(key)
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ThreeDStorageError("3D artifact is unavailable")
            if metadata.st_size != int(size_bytes) or metadata.st_size <= 0:
                raise ThreeDStorageError("3D artifact size verification failed")
            digest = sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except FileNotFoundError as exc:
            raise ThreeDStorageError("3D artifact is unavailable") from exc
        except OSError as exc:
            raise ThreeDStorageError("3D artifact verification failed") from exc
        if not hmac.compare_digest(digest.hexdigest(), expected):
            raise ThreeDStorageError("3D artifact checksum verification failed")
        return path

    def delete(self, key: str) -> None:
        if self.is_local:
            try:
                path = self._local_path(key)
                if not path.is_symlink():
                    path.unlink(missing_ok=True)
            except (OSError, ThreeDStorageError):
                return
            return
        try:
            assert self.client is not None and self.bucket is not None
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError, OSError):
            return

    def presigned_get(
        self,
        key: str,
        *,
        filename: str,
        content_type: str,
        expires_seconds: int,
        inline: bool,
    ) -> str:
        if self.is_local:
            raise ThreeDStorageError(
                "3D local storage uses application-signed artifact links"
            )
        ttl = max(60, min(int(expires_seconds), 3600))
        disposition = "inline" if inline else "attachment"
        safe_name = quote(filename, safe="._-")
        try:
            assert self.client is not None and self.bucket is not None
            return str(
                self.client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": self.bucket,
                        "Key": key,
                        "ResponseContentType": content_type,
                        "ResponseContentDisposition": f"{disposition}; filename*=UTF-8''{safe_name}",
                    },
                    ExpiresIn=ttl,
                )
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ThreeDStorageError(
                f"3D signed URL creation failed: {type(exc).__name__}"
            ) from None

    def preflight(self) -> None:
        if self.is_local:
            assert self.root is not None
            probe = self.root / f".three-d-storage-preflight.{uuid4().hex}"
            try:
                with probe.open("xb") as stream:
                    os.chmod(probe, 0o600)
                    stream.write(b"ok")
                    stream.flush()
                    os.fsync(stream.fileno())
                probe.unlink()
            except OSError as exc:
                with suppress(OSError):
                    probe.unlink(missing_ok=True)
                raise ThreeDStorageError("3D local storage root is not writable") from exc
            return
        try:
            assert self.client is not None and self.bucket is not None
            self.client.head_bucket(Bucket=self.bucket)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ThreeDStorageError(
                f"3D object storage preflight failed: {type(exc).__name__}"
            ) from None
