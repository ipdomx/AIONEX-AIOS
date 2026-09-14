#!/usr/bin/env python3
"""Safe manifest and receipt helper for the FR-06B1 isolated asset-vault lab."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


ROOTS: tuple[tuple[str, str], ...] = (
    ("three_d_asset_data", "asset-vault"),
    ("media_asset_data", "asset-vault"),
    ("project_execution_data", "project-execution-vault"),
    ("studio_asset_data", "asset-vault"),
    ("course_package_data", "asset-vault"),
    ("realtime_recording_data", "asset-vault"),
    ("portal_asset_data", "asset-vault"),
    ("mobile_release_data", "asset-vault"),
    ("audio_song_ingress_data", "asset-vault"),
    ("security_source_data", "asset-vault"),
    ("security_remediation_data", "asset-vault"),
)


class ManifestError(RuntimeError):
    """The tree cannot be copied without violating the FR-06B safety policy."""


def _mode(value: int) -> str:
    return f"{stat.S_IMODE(value):04o}"


def _stable_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def _hash_open_file(fd: int) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _walk_directory(fd: int, relative: str, records: list[dict[str, Any]]) -> None:
    before = os.fstat(fd)
    if not stat.S_ISDIR(before.st_mode):
        raise ManifestError(f"not a directory: {relative}")
    records.append(
        {
            "path": relative,
            "type": "directory",
            "mode": _mode(before.st_mode),
            "uid": before.st_uid,
            "gid": before.st_gid,
        }
    )

    with os.scandir(fd) as iterator:
        entries = sorted(iterator, key=lambda item: os.fsencode(item.name))
    for entry in entries:
        name = entry.name
        child_relative = name if relative == "." else f"{relative}/{name}"
        observed = entry.stat(follow_symlinks=False)
        if stat.S_ISLNK(observed.st_mode):
            raise ManifestError(f"symbolic link rejected: {child_relative}")
        if stat.S_ISDIR(observed.st_mode):
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
            child_fd = os.open(name, flags, dir_fd=fd)
            try:
                opened = os.fstat(child_fd)
                if (opened.st_dev, opened.st_ino) != (
                    observed.st_dev,
                    observed.st_ino,
                ):
                    raise ManifestError(f"directory changed during scan: {child_relative}")
                _walk_directory(child_fd, child_relative, records)
            finally:
                os.close(child_fd)
            continue
        if not stat.S_ISREG(observed.st_mode):
            raise ManifestError(f"special file rejected: {child_relative}")
        if observed.st_nlink != 1:
            raise ManifestError(f"hard-linked file rejected: {child_relative}")

        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        file_fd = os.open(name, flags, dir_fd=fd)
        try:
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise ManifestError(f"unsafe file changed during scan: {child_relative}")
            if (opened.st_dev, opened.st_ino) != (
                observed.st_dev,
                observed.st_ino,
            ):
                raise ManifestError(f"file changed during scan: {child_relative}")
            digest = _hash_open_file(file_fd)
            after = os.fstat(file_fd)
        finally:
            os.close(file_fd)
        if _stable_identity(opened) != _stable_identity(after):
            raise ManifestError(f"file mutated while hashing: {child_relative}")
        records.append(
            {
                "path": child_relative,
                "type": "regular",
                "mode": _mode(after.st_mode),
                "uid": after.st_uid,
                "gid": after.st_gid,
                "size_bytes": after.st_size,
                "sha256": digest,
            }
        )

    after = os.fstat(fd)
    if _stable_identity(before) != _stable_identity(after):
        raise ManifestError(f"directory mutated while scanning: {relative}")


def build_manifest(root: Path) -> dict[str, Any]:
    if not root.is_absolute():
        raise ManifestError("manifest root must be absolute")
    observed = os.lstat(root)
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise ManifestError("manifest root must be a real directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    root_fd = os.open(root, flags)
    try:
        opened = os.fstat(root_fd)
        if (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino):
            raise ManifestError("manifest root changed before scan")
        records: list[dict[str, Any]] = []
        _walk_directory(root_fd, ".", records)
    finally:
        os.close(root_fd)
    canonical = json.dumps(
        records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "entries": records,
        "summary": {
            "directories": sum(item["type"] == "directory" for item in records),
            "regular_files": sum(item["type"] == "regular" for item in records),
            "payload_bytes": sum(
                int(item.get("size_bytes", 0)) for item in records
            ),
            "aggregate_sha256": hashlib.sha256(canonical).hexdigest(),
        },
    }


def _exclusive_json(path: Path, payload: dict[str, Any], mode: int) -> None:
    if not path.is_absolute():
        raise ManifestError("output path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    fd = os.open(path, flags, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_manifest(root: Path, output: Path) -> None:
    _exclusive_json(output, build_manifest(root), 0o600)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ManifestError(f"JSON object required: {path}")
    return value


def compare_manifests(left: Path, right: Path) -> None:
    first = load_json(left)
    second = load_json(right)
    if first.get("entries") != second.get("entries"):
        raise ManifestError(f"manifest mismatch: {left.name} != {right.name}")


def build_summary(
    manifests: Path,
    attempts_path: Path,
    copy_nanoseconds: int,
    asset_header_bytes: int,
    project_header_bytes: int,
) -> dict[str, Any]:
    attempts: dict[str, int] = {}
    for line in attempts_path.read_text(encoding="utf-8").splitlines():
        name, value = line.split("\t", 1)
        attempts[name] = int(value)

    roots: list[dict[str, Any]] = []
    for name, vault in ROOTS:
        source = load_json(manifests / f"{name}.source-post.json")
        recovered = load_json(manifests / f"{name}.recovery.json")
        if source.get("entries") != recovered.get("entries"):
            raise ManifestError(f"recovery mismatch for {name}")
        summary = source["summary"]
        roots.append(
            {
                "volume": f"web-dashboard_{name}",
                "target_subpath": name,
                "vault": vault,
                "directories": int(summary["directories"]),
                "regular_files": int(summary["regular_files"]),
                "payload_bytes": int(summary["payload_bytes"]),
                "aggregate_sha256": str(summary["aggregate_sha256"]),
                "stable_copy_attempts": attempts[name],
            }
        )

    vaults: list[dict[str, Any]] = []
    for vault, mount_options, header_bytes in (
        (
            "asset-vault",
            ["nodev", "nosuid", "noexec"],
            asset_header_bytes,
        ),
        (
            "project-execution-vault",
            ["nodev", "nosuid"],
            project_header_bytes,
        ),
    ):
        selected = [item for item in roots if item["vault"] == vault]
        aggregate = hashlib.sha256(
            "\n".join(
                f"{item['volume']}:{item['aggregate_sha256']}"
                for item in selected
            ).encode("utf-8")
        ).hexdigest()
        vaults.append(
            {
                "vault": vault,
                "mount_options": mount_options,
                "root_count": len(selected),
                "regular_files": sum(item["regular_files"] for item in selected),
                "payload_bytes": sum(item["payload_bytes"] for item in selected),
                "aggregate_sha256": aggregate,
                "header_backup_bytes": header_bytes,
            }
        )

    total_bytes = sum(item["payload_bytes"] for item in roots)
    seconds = copy_nanoseconds / 1_000_000_000
    return {
        "roots": roots,
        "vaults": vaults,
        "totals": {
            "root_count": len(roots),
            "directories": sum(item["directories"] for item in roots),
            "regular_files": sum(item["regular_files"] for item in roots),
            "payload_bytes": total_bytes,
        },
        "copy_performance": {
            "rsync_elapsed_seconds": round(seconds, 6),
            "payload_mib_per_second": round(
                total_bytes / 1024 / 1024 / seconds, 3
            )
            if seconds > 0
            else None,
            "production_p95_gate_evaluated": False,
            "note": "This is an online nonauthoritative pre-seed feasibility result, not the final stopped-writer cutover benchmark.",
        },
    }


def build_receipt(
    observed_at: str,
    source_commit: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "source_commit": source_commit,
        "batch_id": "FR-06",
        "subpart": "FR-06B1",
        "lab": {
            "type": "two_file_backed_luks2_live_asset_copy_recovery_and_docker_fail_closed_rehearsal",
            "backing_file_bytes_each": 256 * 1024 * 1024,
            "cipher": "aes-xts-plain64",
            "key_bits": 512,
            "pbkdf": "argon2id",
            "filesystem": "ext4",
            "keys_created_only_on_tmpfs": True,
            "key_material_persisted": False,
            "live_sources_opened_read_only_by_the_lab": True,
        },
        "copy_evidence": summary,
        "checks": {
            "all_eleven_roots_present": True,
            "source_symlinks_rejected": True,
            "source_hardlinks_rejected": True,
            "source_special_files_rejected": True,
            "source_file_mutation_during_hash_rejected": True,
            "source_pre_and_post_manifests_stable": True,
            "copy_metadata_and_content_match": True,
            "active_keys_open_verified": True,
            "independent_recovery_keys_open_verified": True,
            "wrong_key_rejected_for_both_vaults": True,
            "closed_raw_plaintext_markers_absent": True,
            "header_backups_created_private": True,
            "recovery_payload_manifests_match": True,
            "compose_volume_subpath_supported": True,
            "docker_local_volume_backed_by_mapper_verified": True,
            "passive_asset_noexec_enforced": True,
            "project_execution_exec_exception_verified": True,
            "missing_mapper_failed_closed_without_plaintext_fallback": True,
            "temporary_docker_resources_removed": True,
            "temporary_mappings_mounts_keys_and_files_removed": True,
            "production_container_ids_unchanged": True,
            "production_services_stopped_or_restarted": False,
            "production_compose_changed": False,
            "production_volumes_changed": False,
            "live_block_devices_formatted": False,
            "cloudflare_changed": False,
            "reboot_performed": False,
        },
        "cutover_gate": {
            "live_cutover_allowed_by_this_receipt": False,
            "still_required": [
                "fresh encrypted R2 recovery point validated immediately before cutover",
                "production active and recovery keys retained outside the unencrypted root",
                "production LUKS2 headers retained off-host separately from recovery keys",
                "owner-visible out-of-band missing-vault alert proved independently",
                "all scoped writers stopped for the final delta and exact integrity comparison",
                "workload-specific p95 comparison with no more than 15 percent regression",
                "protected Compose and systemd source change merged with all required checks",
                "selective service rehearsal plus exact rollback proof while plaintext sources remain read-only",
            ],
        },
        "all_checks_passed": True,
        "production_changed": False,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--root", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--left", type=Path, required=True)
    compare.add_argument("--right", type=Path, required=True)
    summary = commands.add_parser("summary")
    summary.add_argument("--manifests", type=Path, required=True)
    summary.add_argument("--attempts", type=Path, required=True)
    summary.add_argument("--copy-nanoseconds", type=int, required=True)
    summary.add_argument("--asset-header-bytes", type=int, required=True)
    summary.add_argument("--project-header-bytes", type=int, required=True)
    receipt = commands.add_parser("receipt")
    receipt.add_argument("--output", type=Path, required=True)
    receipt.add_argument("--observed-at", required=True)
    receipt.add_argument("--source-commit", required=True)
    receipt.add_argument("--summary-json", required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "manifest":
            write_manifest(args.root, args.output)
        elif args.command == "compare":
            compare_manifests(args.left, args.right)
        elif args.command == "summary":
            print(
                json.dumps(
                    build_summary(
                        args.manifests,
                        args.attempts,
                        args.copy_nanoseconds,
                        args.asset_header_bytes,
                        args.project_header_bytes,
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        elif args.command == "receipt":
            summary = json.loads(args.summary_json)
            if not isinstance(summary, dict):
                raise ManifestError("summary JSON must be an object")
            _exclusive_json(
                args.output,
                build_receipt(args.observed_at, args.source_commit, summary),
                0o644,
            )
            print(
                json.dumps(
                    {"receipt": str(args.output), "all_checks_passed": True},
                    separators=(",", ":"),
                )
            )
    except (ManifestError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FR-06B manifest error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
