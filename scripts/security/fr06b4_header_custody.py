#!/usr/bin/env python3
"""Upload and fully read back the two FR-06B4 LUKS2 headers in private R2.

Designed to run inside the existing backup-worker container, where the private
R2 credential source is already mounted. It accepts only the two fixed header
files copied into container tmpfs and never reads a LUKS key bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


INPUT_ROOT = Path("/run/aionex-fr06b4-headers")
DEFAULT_CREDENTIALS = Path("/run/operator-secrets/r2-backup-source.env")
HEADER_FILES = {
    "asset-vault": "aionex-asset-vault.header",
    "project-execution-vault": "aionex-project-execution-vault.header",
}
ALLOWED_CREDENTIALS = {
    "R2_BACKUP_ENDPOINT",
    "R2_BACKUP_BUCKET",
    "R2_BACKUP_ACCESS_KEY_ID",
    "R2_BACKUP_SECRET_ACCESS_KEY",
}
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
GENERATION_RE = re.compile(r"^[0-9a-f]{32}$")
PREFIX_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,180}$")
CHUNK = 1024 * 1024


class CustodyError(RuntimeError):
    pass


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _private_file(path: Path, label: str, maximum: int) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise CustodyError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise CustodyError(f"{label} must be a single-link regular file")
    if info.st_uid != os.geteuid() or info.st_mode & 0o077 or not 1 <= info.st_size <= maximum:
        raise CustodyError(f"{label} permissions or size are unsafe")
    return info


def _credentials(path: Path) -> dict[str, str]:
    _private_file(path, "credential source", 64 * 1024)
    values: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or key not in ALLOWED_CREDENTIALS or key in values or not value:
                raise CustodyError("credential source fields are invalid")
            values[key] = value
    except (OSError, UnicodeError) as exc:
        raise CustodyError("credential source could not be read") from exc
    if set(values) != ALLOWED_CREDENTIALS:
        raise CustodyError("credential source is incomplete")
    endpoint = urlparse(values["R2_BACKUP_ENDPOINT"])
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or not endpoint.hostname.endswith(".r2.cloudflarestorage.com")
        or endpoint.username
        or endpoint.password
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
    ):
        raise CustodyError("R2 endpoint is not approved")
    if BUCKET_RE.fullmatch(values["R2_BACKUP_BUCKET"]) is None:
        raise CustodyError("R2 bucket is invalid")
    return values


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.geteuid()
            or opened.st_mode & 0o077
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise CustodyError("header changed or became unsafe while opening")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            magic = stream.read(6)
            if magic != b"LUKS\xba\xbe":
                raise CustodyError("header does not have LUKS magic")
            digest.update(magic)
            size += len(magic)
            for chunk in iter(lambda: stream.read(CHUNK), b""):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


def _missing(client: Any, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        response = getattr(exc, "response", {})
        code = str((response.get("Error") or {}).get("Code", "")) if isinstance(response, dict) else ""
        if code in {"404", "NoSuchKey", "NotFound"}:
            return True
        raise CustodyError("cannot establish that the header object is new") from exc
    return False


def _upload_one(client: Any, bucket: str, key: str, role: str, path: Path) -> dict[str, Any]:
    info = _private_file(path, f"{role} header", 32 * 1024 * 1024)
    checksum, size = _sha256(path)
    if info.st_size != size:
        raise CustodyError(f"{role} header changed while being read")
    if not _missing(client, bucket, key):
        raise CustodyError(f"{role} header object already exists")
    metadata = {"sha256": checksum, "aionex-subpart": "fr-06b4", "vault-role": role}
    try:
        with path.open("rb") as stream:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=stream,
                ContentLength=size,
                ContentType="application/octet-stream",
                Metadata=metadata,
                IfNoneMatch="*",
            )
        head = client.head_object(Bucket=bucket, Key=key)
        remote_metadata = {str(k).lower(): str(v) for k, v in (head.get("Metadata") or {}).items()}
        if int(head.get("ContentLength", -1)) != size or any(remote_metadata.get(k) != v for k, v in metadata.items()):
            raise CustodyError(f"{role} header metadata read-back failed")
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        remote_digest = hashlib.sha256()
        remote_size = 0
        try:
            for chunk in iter(lambda: body.read(CHUNK), b""):
                remote_digest.update(chunk)
                remote_size += len(chunk)
        finally:
            body.close()
        if remote_size != size or remote_digest.hexdigest() != checksum:
            raise CustodyError(f"{role} full header read-back failed")
    except CustodyError:
        raise
    except Exception as exc:
        raise CustodyError(f"{role} header upload or verification failed") from exc
    return {
        "role": role,
        "reference": f"r2://{bucket}/{key}",
        "object_key": key,
        "sha256": checksum,
        "size_bytes": size,
        "head_metadata_matched": True,
        "full_readback_matched": True,
    }


def upload(args: argparse.Namespace, client: Any | None = None) -> dict[str, Any]:
    if GENERATION_RE.fullmatch(args.generation) is None:
        raise CustodyError("generation must be 32 lowercase hexadecimal characters")
    prefix = args.prefix.strip("/")
    if PREFIX_RE.fullmatch(prefix) is None or ".." in prefix.split("/"):
        raise CustodyError("object prefix is invalid")
    credentials = _credentials(args.credentials.resolve())
    bucket = credentials["R2_BACKUP_BUCKET"]
    if client is None:
        try:
            import boto3  # type: ignore[import-untyped]
            from botocore.config import Config  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CustodyError("boto3 is unavailable in this execution boundary") from exc
        client = boto3.client(
            "s3",
            endpoint_url=credentials["R2_BACKUP_ENDPOINT"],
            aws_access_key_id=credentials["R2_BACKUP_ACCESS_KEY_ID"],
            aws_secret_access_key=credentials["R2_BACKUP_SECRET_ACCESS_KEY"],
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 4, "mode": "standard"}, connect_timeout=10, read_timeout=120),
        )
    try:
        client.head_bucket(Bucket=bucket)
    except Exception as exc:
        raise CustodyError("private R2 bucket is unreachable with configured authority") from exc
    objects: list[dict[str, Any]] = []
    for role, filename in HEADER_FILES.items():
        path = INPUT_ROOT / filename
        if path.resolve(strict=True).parent != INPUT_ROOT:
            raise CustodyError(f"{role} header escaped the fixed input root")
        key = f"{prefix}/fr06b4/luks2-headers/{args.generation}/{filename}"
        objects.append(_upload_one(client, bucket, key, role, path))
    return {
        "schema_version": 1,
        "subpart": "FR-06B4",
        "status": "off_host_headers_verified",
        "generation": args.generation,
        "observed_at": _utc(),
        "objects": objects,
        "object_count": 2,
        "references_distinct": len({item["reference"] for item in objects}) == 2,
        "recovery_keys_stored_in_r2": False,
        "header_plaintext_payload_present": False,
        "full_readback_verified": True,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--generation", required=True)
    value.add_argument("--prefix", default="aionex-production")
    value.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    return value


def main() -> int:
    try:
        result = upload(parser().parse_args())
    except CustodyError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
