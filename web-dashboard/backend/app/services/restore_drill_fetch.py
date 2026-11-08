"""P6 gate 6.4 restore drill: fetch + decrypt the newest R2 backup, extract assets.

Runs ONLY inside the throwaway ``aionex-restore-drill-*`` compose project
(``deploy/restore-drill/docker-compose.restore-drill.yml``), never in a
production container.  It reuses the production code paths unchanged:

* ``OffsiteBackupReplicator`` (credential-file checks, AES-256-GCM envelope,
  ciphertext + plaintext SHA-256 verification) and
* the platform-asset snapshot layout ``files/<root_id>/<relative>`` written by
  ``three_d_asset_backup``.

``fetch`` locates the newest complete encrypted prefix by its
``manifest.json.aex1`` object (the same rule ``prune`` uses), authenticates the
manifest by decrypting it under its exact R2 key context, then downloads the
database dump and asset snapshot through ``download_for_validation``.
``extract`` unpacks the asset snapshot into per-root directories with strict
member checks.  Neither command prints a secret.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

ASSET_ROOTS = (
    "three_d_asset_data",
    "project_execution_data",
    "course_package_data",
    "media_asset_data",
    "studio_asset_data",
    "portal_asset_data",
    "mobile_release_data",
    "realtime_recording_data",
    "audio_song_ingress_data",
    "security_source_data",
    "security_remediation_data",
)
DATABASE_NAME = "drill-database.dump"
ASSETS_NAME = "drill-assets.tar"
SUMMARY_NAME = "drill-summary.json"


class DrillFetchError(RuntimeError):
    """The drill fetch/extract refused or failed; nothing outside the drill was touched."""


def _newest_manifest(replicator: Any) -> tuple[str, str]:
    paginator = replicator.client.get_paginator("list_objects_v2")
    newest: tuple[Any, str] | None = None
    for page in paginator.paginate(Bucket=replicator._bucket, Prefix=f"{replicator._prefix}/"):
        for item in page.get("Contents", []):
            key = str(item.get("Key", ""))
            if not key.endswith("/manifest.json.aex1"):
                continue
            modified = item.get("LastModified")
            if newest is None or modified > newest[0]:
                newest = (modified, key)
    if newest is None:
        raise DrillFetchError("no encrypted backup manifest exists under the configured prefix")
    key = newest[1]
    backup_id = key[len(replicator._prefix) + 1:].split("/", 1)[0]
    if replicator._key(backup_id, "manifest.json.aex1") != key:
        raise DrillFetchError("newest manifest key does not match the backup id layout")
    return backup_id, key


def fetch(backup_dir: Path) -> dict[str, Any]:
    from app.core.config import settings
    from app.services.offsite_backup import OffsiteBackupReplicator
    from app.services.offsite_encryption import EncryptionContext

    if Path(settings.BACKUP_DIR).resolve() != backup_dir.resolve():
        raise DrillFetchError("BACKUP_DIR must be the drill scratch directory")
    replicator = OffsiteBackupReplicator(settings)
    if not replicator.enabled:
        raise DrillFetchError("BACKUP_OFFSITE_ENABLED must be true for the drill fetch")
    backup_id, manifest_key = _newest_manifest(replicator)
    encrypted = backup_dir / ".drill-manifest.json.aex1"
    plaintext = backup_dir / ".drill-manifest.json"
    replicator.client.download_file(replicator._bucket, manifest_key, str(encrypted))
    os.chmod(encrypted, 0o600)
    replicator.encryption.decrypt_file(
        encrypted,
        plaintext,
        context=EncryptionContext(backup_id=backup_id, object_role="manifest", r2_object_key=manifest_key),
    )
    manifest = json.loads(plaintext.read_text(encoding="utf-8"))
    encrypted.unlink(missing_ok=True)
    plaintext.unlink(missing_ok=True)
    if manifest.get("backup_id") != backup_id or manifest.get("schema_version") != 2:
        raise DrillFetchError("authenticated manifest does not describe the expected backup")
    evidence = {
        "schema_version": 2,
        "backup_id": backup_id,
        "encryption_required": True,
        "database": manifest["database"],
        "three_d_snapshot": manifest.get("platform_asset_snapshot"),
    }
    artifacts = replicator.download_for_validation(
        evidence, validation_id="p6-restore-drill", attempt_token=secrets.token_hex(16)
    )
    database = backup_dir / DATABASE_NAME
    os.replace(artifacts.database_location, database)
    assets = None
    if artifacts.snapshot_location:
        assets = backup_dir / ASSETS_NAME
        os.replace(artifacts.snapshot_location, assets)
    snapshot = manifest.get("platform_asset_snapshot") or {}
    summary = {
        "backup_id": backup_id,
        "backup_created_at": manifest.get("created_at"),
        "database": {"sha256": manifest["database"]["sha256"], "size_bytes": manifest["database"]["size_bytes"],
                     "file": DATABASE_NAME},
        "assets": (
            {"sha256": snapshot.get("sha256"), "size_bytes": snapshot.get("size_bytes"),
             "file_count": snapshot.get("file_count"), "roots": snapshot.get("roots"), "file": ASSETS_NAME}
            if assets else None
        ),
        "verified": "ciphertext and plaintext SHA-256 + AES-256-GCM tag (OffsiteBackupReplicator)",
    }
    (backup_dir / SUMMARY_NAME).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def safe_member_target(name: str, destination: Path) -> tuple[str, Path]:
    path = PurePosixPath(name)
    parts = path.parts
    if len(parts) < 3 or parts[0] != "files" or parts[1] not in ASSET_ROOTS:
        raise DrillFetchError(f"unexpected archive member layout: {name!r}")
    if any(part in ("", ".", "..") for part in parts) or path.is_absolute():
        raise DrillFetchError(f"unsafe archive member path: {name!r}")
    target = destination.joinpath(*parts[1:])
    if destination.resolve() not in target.resolve().parents:
        raise DrillFetchError(f"archive member escapes destination: {name!r}")
    return parts[1], target


def extract(archive: Path, destination: Path) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {}
    with tarfile.open(archive, mode="r:") as bundle:
        for member in bundle:
            if member.isdir():
                continue
            if member.name == "manifest.json" and member.isreg():
                continue  # snapshot inventory written by three_d_asset_backup
            if not member.isreg():
                raise DrillFetchError(f"archive member is not a regular file: {member.name!r}")
            root, target = safe_member_target(member.name, destination)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            source = bundle.extractfile(member)
            if source is None:
                raise DrillFetchError(f"archive member unreadable: {member.name!r}")
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o640)
            with os.fdopen(descriptor, "wb") as sink:
                while chunk := source.read(1024 * 1024):
                    sink.write(chunk)
            entry = counts.setdefault(root, {"files": 0, "bytes": 0})
            entry["files"] += 1
            entry["bytes"] += member.size
    # The backend entrypoint requires every storage root to be 700 and owned by the
    # service user, and the drill mounts /restore read-only, so it cannot fix them
    # itself. Create each root (even ones the backup had no files for) as private.
    for root in ASSET_ROOTS:
        path = destination / root
        path.mkdir(exist_ok=True, mode=0o700)
        if path.is_symlink() or not path.is_dir():
            raise DrillFetchError(f"restored root is not a directory: {root!r}")
        os.chmod(path, 0o700)
    return {"roots": counts, "files": sum(v["files"] for v in counts.values())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_cmd = sub.add_parser("fetch")
    fetch_cmd.add_argument("--backup-dir", type=Path, required=True)
    extract_cmd = sub.add_parser("extract")
    extract_cmd.add_argument("--archive", type=Path, required=True)
    extract_cmd.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get("AIOS_RESTORE_DRILL") != "1":
        print(json.dumps({"status": "REFUSED", "reason": "only runs inside the restore-drill compose project"}),
              file=sys.stderr)
        return 2
    try:
        if args.command == "fetch":
            result = fetch(args.backup_dir)
        else:
            if args.destination.exists() and any(args.destination.iterdir()):
                raise DrillFetchError("extraction destination must be empty")
            if stat.S_ISLNK(args.archive.lstat().st_mode):
                raise DrillFetchError("archive must not be a symlink")
            result = extract(args.archive, args.destination)
    except (DrillFetchError, OSError, KeyError, ValueError, tarfile.TarError) as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__, "detail": str(exc)[:300]}),
              file=sys.stderr)
        return 1
    print(json.dumps({"status": "OK", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
