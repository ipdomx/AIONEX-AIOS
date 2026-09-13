#!/usr/bin/env python3
"""FR-04D asset-root preflight without reading file contents.

The preflight validates only metadata: path type, ownership, permissions,
link count, symlink/special-file absence, file counts and declared sizes.  It is
safe to run inside backup-worker before a full backup acceptance because it does
not open or hash user files.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import sys
from typing import Iterable


@dataclass(frozen=True, slots=True)
class RootPolicy:
    root_id: str
    path: Path
    directory_mode: int = 0o700
    file_mode: int = 0o600
    owner_uid: int = 1000
    group_gid: int = 1000


DEFAULT_ROOTS: tuple[RootPolicy, ...] = (
    RootPolicy("three_d_asset_data", Path("/var/lib/aionex/three-d-assets")),
    RootPolicy("project_execution_data", Path("/var/lib/aionex/project-executions")),
    RootPolicy("course_package_data", Path("/var/lib/aionex/course-packages")),
    RootPolicy("media_asset_data", Path("/var/lib/aionex/media-assets")),
    RootPolicy("studio_asset_data", Path("/var/lib/aionex/studio-assets")),
    RootPolicy("portal_asset_data", Path("/var/lib/aionex/portal-assets")),
    RootPolicy("mobile_release_data", Path("/var/lib/aionex/mobile-releases")),
    RootPolicy(
        "realtime_recording_data",
        Path("/var/lib/aionex/realtime-recordings"),
        directory_mode=0o2770,
        file_mode=0o660,
        owner_uid=1001,
        group_gid=1000,
    ),
    RootPolicy("audio_song_ingress_data", Path("/var/lib/aionex/audio-song-provider-ingress")),
    RootPolicy("security_source_data", Path("/var/lib/aionex/security-sources")),
    RootPolicy("security_remediation_data", Path("/var/lib/aionex/security-remediations")),
)


@dataclass(slots=True)
class RootCensus:
    root_id: str
    path: str
    file_count: int = 0
    directory_count: int = 0
    payload_bytes: int = 0
    symlink_count: int = 0
    special_count: int = 0
    hardlinked_file_count: int = 0
    unsafe_permission_count: int = 0
    unreadable_file_count: int = 0

    @property
    def ok(self) -> bool:
        return not any(
            (
                self.symlink_count,
                self.special_count,
                self.hardlinked_file_count,
                self.unsafe_permission_count,
                self.unreadable_file_count,
            )
        )

    def to_json(self) -> dict[str, int | str | bool]:
        return {
            "root_id": self.root_id,
            "path": self.path,
            "file_count": self.file_count,
            "directory_count": self.directory_count,
            "payload_bytes": self.payload_bytes,
            "symlink_count": self.symlink_count,
            "special_count": self.special_count,
            "hardlinked_file_count": self.hardlinked_file_count,
            "unsafe_permission_count": self.unsafe_permission_count,
            "unreadable_file_count": self.unreadable_file_count,
            "ok": self.ok,
        }


def _mode(metadata: os.stat_result) -> int:
    return stat.S_IMODE(metadata.st_mode)


def _allowed(metadata: os.stat_result, policy: RootPolicy, *, is_directory: bool) -> bool:
    expected_mode = policy.directory_mode if is_directory else policy.file_mode
    return (
        _mode(metadata) == expected_mode
        and metadata.st_uid == policy.owner_uid
        and metadata.st_gid == policy.group_gid
    )


def census_root(policy: RootPolicy) -> RootCensus:
    census = RootCensus(root_id=policy.root_id, path=str(policy.path))
    try:
        root_meta = policy.path.lstat()
    except OSError:
        census.special_count += 1
        return census
    if stat.S_ISLNK(root_meta.st_mode) or not stat.S_ISDIR(root_meta.st_mode):
        census.special_count += 1
        return census
    if not _allowed(policy.path.stat(), policy, is_directory=True):
        census.unsafe_permission_count += 1
    if not os.access(policy.path, os.R_OK | os.X_OK):
        census.unsafe_permission_count += 1
    census.directory_count += 1

    for current, dir_names, file_names in os.walk(policy.path, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in dir_names:
            candidate = current_path / name
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                census.symlink_count += 1
                continue
            if not stat.S_ISDIR(metadata.st_mode):
                census.special_count += 1
                continue
            if not _allowed(metadata, policy, is_directory=True):
                census.unsafe_permission_count += 1
            census.directory_count += 1
            kept_dirs.append(name)
        dir_names[:] = kept_dirs

        for name in file_names:
            candidate = current_path / name
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                census.symlink_count += 1
                continue
            if not stat.S_ISREG(metadata.st_mode):
                census.special_count += 1
                continue
            if metadata.st_nlink != 1:
                census.hardlinked_file_count += 1
            if not _allowed(metadata, policy, is_directory=False):
                census.unsafe_permission_count += 1
            if not os.access(candidate, os.R_OK):
                census.unreadable_file_count += 1
            census.file_count += 1
            census.payload_bytes += int(metadata.st_size)
    return census


def preflight(roots: Iterable[RootPolicy] = DEFAULT_ROOTS) -> dict[str, object]:
    root_results = [census_root(policy) for policy in roots]
    totals = {
        "file_count": sum(item.file_count for item in root_results),
        "directory_count": sum(item.directory_count for item in root_results),
        "payload_bytes": sum(item.payload_bytes for item in root_results),
        "symlink_count": sum(item.symlink_count for item in root_results),
        "special_count": sum(item.special_count for item in root_results),
        "hardlinked_file_count": sum(item.hardlinked_file_count for item in root_results),
        "unsafe_permission_count": sum(item.unsafe_permission_count for item in root_results),
        "unreadable_file_count": sum(item.unreadable_file_count for item in root_results),
    }
    return {
        "schema_version": 1,
        "kind": "aionex-fr04d-asset-preflight",
        "content_read": False,
        "hashes_computed": False,
        "root_count": len(root_results),
        "status": "pass" if all(item.ok for item in root_results) else "fail",
        "totals": totals,
        "roots": [item.to_json() for item in root_results],
    }


def _load_roots(path: Path | None) -> tuple[RootPolicy, ...]:
    if path is None:
        return DEFAULT_ROOTS
    raw = json.loads(path.read_text(encoding="utf-8"))
    roots: list[RootPolicy] = []
    for item in raw:
        roots.append(
            RootPolicy(
                root_id=str(item["root_id"]),
                path=Path(item["path"]),
                directory_mode=int(str(item.get("directory_mode", "0700")), 8),
                file_mode=int(str(item.get("file_mode", "0600")), 8),
                owner_uid=int(item.get("owner_uid", 1000)),
                group_gid=int(item.get("group_gid", 1000)),
            )
        )
    return tuple(roots)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roots-json", type=Path, default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = preflight(_load_roots(args.roots_json))
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
