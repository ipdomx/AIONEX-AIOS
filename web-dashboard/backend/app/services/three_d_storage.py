"""Private S3 object storage for user 3D inputs and generated artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Final
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

GLB_MEDIA_TYPE: Final = "model/gltf-binary"


class ThreeDStorageError(RuntimeError):
    """Sanitized 3D storage failure."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str
    content_type: str


class ThreeDObjectStore:
    def __init__(self) -> None:
        if settings.STORAGE_TYPE.strip().lower() != "s3":
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
        try:
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
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            declared = int(response.get("ContentLength") or 0)
            if declared <= 0 or declared > max_bytes:
                raise ThreeDStorageError("3D object size is outside the allowed range")
            body = response["Body"].read(max_bytes + 1)
        except ThreeDStorageError:
            raise
        except (BotoCoreError, ClientError, OSError, KeyError) as exc:
            raise ThreeDStorageError(
                f"3D object download failed: {type(exc).__name__}"
            ) from None
        if len(body) > max_bytes:
            raise ThreeDStorageError("3D object exceeds the allowed size")
        return body

    def delete(self, key: str) -> None:
        try:
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
        ttl = max(60, min(int(expires_seconds), 3600))
        disposition = "inline" if inline else "attachment"
        safe_name = quote(filename, safe="._-")
        try:
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
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ThreeDStorageError(
                f"3D object storage preflight failed: {type(exc).__name__}"
            ) from None
