"""Durable mobile/PWA release registry for Phase 29H."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    MobileRelease,
    MobileReleaseArtifact,
    MobileValidationRun,
    uuid_str,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

SCHEMA = "aionex.mobile-release.v1"
PLATFORMS = frozenset({"pwa", "android", "ios"})


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def release_root() -> Path:
    root = Path(settings.MOBILE_RELEASE_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _safe_path(relative: str) -> Path:
    root = release_root()
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise ValueError("Mobile release artifact path is invalid")
    return candidate


def checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(path: str, checksum: str, size_bytes: int) -> Path:
    candidate = _safe_path(path)
    if candidate.stat().st_size != size_bytes:
        raise ValueError("Mobile release artifact size verification failed")
    if checksum_file(candidate) != checksum:
        raise ValueError("Mobile release artifact checksum verification failed")
    return candidate


def release_snapshot(item: MobileRelease, artifacts: list[MobileReleaseArtifact], validations: list[MobileValidationRun]) -> dict[str, Any]:
    return {
        "id": item.id,
        "platform": item.platform,
        "version": item.version,
        "build_number": item.build_number,
        "channel": item.channel,
        "status": item.status,
        "signing_status": item.signing_status,
        "publication_status": item.publication_status,
        "source_commit": item.source_commit,
        "manifest_checksum": item.manifest_checksum,
        "metadata": item.release_metadata,
        "built_at": iso(item.built_at),
        "validated_at": iso(item.validated_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
        "artifacts": [
            {
                "id": artifact.id,
                "artifact_type": artifact.artifact_type,
                "filename": artifact.filename,
                "media_type": artifact.media_type,
                "checksum": artifact.checksum,
                "size_bytes": artifact.size_bytes,
                "signed": artifact.signed,
                "signature_metadata": artifact.signature_metadata,
                "status": artifact.status,
                "created_at": iso(artifact.created_at),
            }
            for artifact in artifacts
        ],
        "validations": [
            {
                "id": validation.id,
                "operation": validation.operation,
                "status": validation.status,
                "evidence": validation.evidence,
                "completed_at": iso(validation.completed_at),
                "created_at": iso(validation.created_at),
            }
            for validation in validations
        ],
    }


async def register_manifest(session: AsyncSession, manifest_path: str | Path) -> list[MobileRelease]:
    root = release_root()
    manifest = Path(manifest_path).resolve()
    if root not in manifest.parents or not manifest.is_file():
        raise ValueError("Mobile release manifest must be inside MOBILE_RELEASE_ROOT")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError("Unsupported mobile release manifest schema")
    source_commit = str(payload.get("source_commit", "")).strip().lower()
    if len(source_commit) < 7 or any(char not in "0123456789abcdef" for char in source_commit):
        raise ValueError("Mobile release source commit is invalid")
    manifest_checksum = checksum_file(manifest)
    releases: list[MobileRelease] = []
    for release_data in payload.get("releases", []):
        platform = str(release_data.get("platform", "")).strip().lower()
        if platform not in PLATFORMS:
            raise ValueError("Unsupported mobile release platform")
        version = str(release_data.get("version", "")).strip()
        build_number = int(release_data.get("build_number", 0))
        channel = str(release_data.get("channel", "internal")).strip().lower()
        if not version or build_number <= 0 or not channel:
            raise ValueError("Mobile release identity is incomplete")
        item = await session.scalar(
            select(MobileRelease).where(
                MobileRelease.platform == platform,
                MobileRelease.version == version,
                MobileRelease.build_number == build_number,
                MobileRelease.channel == channel,
            )
        )
        if item is None:
            item = MobileRelease(
                id=uuid_str(),
                platform=platform,
                version=version,
                build_number=build_number,
                channel=channel,
                status=str(release_data.get("status", "validated")),
                signing_status=str(release_data.get("signing_status", "not_applicable")),
                publication_status=str(release_data.get("publication_status", "not_published")),
                source_commit=source_commit,
                manifest_path=str(manifest.relative_to(root)),
                manifest_checksum=manifest_checksum,
                release_metadata=dict(release_data.get("metadata") or {}),
                built_at=now(),
                validated_at=now(),
            )
            session.add(item)
            await session.flush()
        else:
            item.status = str(release_data.get("status", item.status))
            item.signing_status = str(release_data.get("signing_status", item.signing_status))
            item.publication_status = str(release_data.get("publication_status", item.publication_status))
            item.source_commit = source_commit
            item.manifest_path = str(manifest.relative_to(root))
            item.manifest_checksum = manifest_checksum
            item.release_metadata = dict(release_data.get("metadata") or {})
            item.built_at = now()
            item.validated_at = now()
            await session.execute(delete(MobileReleaseArtifact).where(MobileReleaseArtifact.release_id == item.id))
            await session.execute(delete(MobileValidationRun).where(MobileValidationRun.release_id == item.id))

        for artifact_data in release_data.get("artifacts", []):
            relative = str(artifact_data.get("path", "")).strip()
            path = _safe_path(relative)
            expected_checksum = str(artifact_data.get("sha256", "")).strip().lower()
            expected_size = int(artifact_data.get("size_bytes", 0))
            if expected_checksum != checksum_file(path) or expected_size != path.stat().st_size:
                raise ValueError(f"Mobile artifact integrity failed: {relative}")
            session.add(
                MobileReleaseArtifact(
                    id=uuid_str(),
                    release_id=item.id,
                    artifact_type=str(artifact_data.get("type", "artifact")),
                    filename=path.name,
                    storage_path=relative,
                    media_type=str(artifact_data.get("media_type", "application/octet-stream")),
                    checksum=expected_checksum,
                    size_bytes=expected_size,
                    signed=bool(artifact_data.get("signed", False)),
                    signature_metadata=dict(artifact_data.get("signature") or {}),
                    status="ready",
                )
            )
        for validation_data in release_data.get("validations", []):
            session.add(
                MobileValidationRun(
                    id=uuid_str(),
                    release_id=item.id,
                    operation=str(validation_data.get("operation", "validation")),
                    status=str(validation_data.get("status", "passed")),
                    evidence=dict(validation_data.get("evidence") or {}),
                    completed_at=now(),
                )
            )
        session.add(
            AuditEvent(
                organization_id=None,
                user_id=None,
                action="mobile.release.registered",
                resource_type="mobile_release",
                resource_id=item.id,
                details={
                    "platform": platform,
                    "version": version,
                    "build_number": build_number,
                    "status": item.status,
                    "signing_status": item.signing_status,
                    "publication_status": item.publication_status,
                    "source_commit": source_commit,
                },
            )
        )
        releases.append(item)
    await session.commit()
    return releases


async def async_main(path: str) -> int:
    async with SessionLocal() as session:
        items = await register_manifest(session, path)
        print(json.dumps({"registered": len(items), "platforms": sorted(item.platform for item in items)}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", required=True)
    args = parser.parse_args()
    return asyncio.run(async_main(args.register))


if __name__ == "__main__":
    raise SystemExit(main())
