#!/usr/bin/env python3
"""Source-custody guard for the NS12 G7 post-anomaly DNS diagnostic fix.

This prepares an immutable create-only diagnostic source. It does not change a
systemd unit, its timer, any historical observation, release status, endpoints,
probe thresholds, container generation, provider session, or customer record.
Default mode is verification only; --prepare must be explicitly selected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

ROOT = Path("/var/lib/aionex-migration/ns12-local-monitoring-20261008")
ORIGINAL = ROOT / "ns12_observer_v9_g7.py"
PREPARED = ROOT / "ns12_observer_v10_g7_diagnostic_only.py"

SOURCE_SHA256 = "bf37dcb71dffe3fc35fd7ef3307c6b88aa96c32f145ab644882af41f538a4185"
PREPARED_SHA256 = "f04fac6947e5619e8f3f901642fc9c30ca9013fb7eb4879d3fab703ba5b25d88"

# [REDACTED] is a malformed literal in the historical source, not a credential:
# it raises NameError while parsing getent's first IPv4 token.
DEFECT = b'token = [REDACTED] if line.split() else ""'
REPAIR = b'token = line.split()[0] if line.split() else ""'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guarded_patch(data: bytes, *, original_sha256: str, prepared_sha256: str) -> bytes:
    """Allow exactly the reviewed one-line repair of the pinned source."""
    if sha256(data) != original_sha256:
        raise ValueError("historical NS12 source SHA does not match")
    if data.count(DEFECT) != 1:
        raise ValueError("NS12 post-anomaly diagnostic preimage not unique")
    fixed = data.replace(DEFECT, REPAIR, 1)
    if sha256(fixed) != prepared_sha256:
        raise ValueError("corrected NS12 source SHA does not match")
    return fixed


def prepare(
    original: Path,
    prepared: Path,
    *,
    original_sha256: str,
    prepared_sha256: str,
) -> str:
    """Create-only write with explicit target/readback checks; no activation."""
    if original.is_symlink() or prepared.is_symlink():
        raise ValueError("NS12 source paths cannot be symlinks")
    if not original.is_file():
        raise ValueError("NS12 original version is missing")
    if original.resolve().parent != prepared.resolve().parent:
        raise ValueError("NS12 source versions must share the same directory")
    fixed = guarded_patch(
        original.read_bytes(),
        original_sha256=original_sha256,
        prepared_sha256=prepared_sha256,
    )
    if prepared.exists():
        current = prepared.read_bytes()
        mode = stat.S_IMODE(prepared.stat().st_mode)
        if sha256(current) != prepared_sha256 or mode != 0o600:
            raise ValueError("existing staged NS12 source differs from reviewed output")
        return "ALREADY_PREPARED_EXACT"
    fd = os.open(
        prepared, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(fixed)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(prepared, 0o600)
        if sha256(prepared.read_bytes()) != prepared_sha256:
            raise ValueError("newly prepared NS12 source readback mismatch")
        directory_fd = os.open(prepared.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        prepared.unlink(missing_ok=True)
        raise
    return "CREATED_EXACT_UNACTIVATED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("root-owned source custody verification is required")
    original = ORIGINAL
    staged = PREPARED
    if args.prepare:
        result = prepare(
            original, staged,
            original_sha256=SOURCE_SHA256,
            prepared_sha256=PREPARED_SHA256,
        )
    else:
        guarded_patch(
            original.read_bytes(),
            original_sha256=SOURCE_SHA256,
            prepared_sha256=PREPARED_SHA256,
        )
        if staged.exists():
            if staged.is_symlink() or not staged.is_file():
                raise ValueError("staged source file is not regular")
            if sha256(staged.read_bytes()) != PREPARED_SHA256:
                raise ValueError("staged source bytes mismatch")
            if stat.S_IMODE(staged.stat().st_mode) != 0o600:
                raise ValueError("staged source permissions differ")
            result = "ALREADY_PREPARED_EXACT"
        else:
            result = "CAN_PREPARE"
    print(json.dumps({
        "schema": "aionex.ns12.g7.diagnostic-source-custody.v1",
        "status": result,
        "original_source_sha256": SOURCE_SHA256,
        "prepared_source_sha256": PREPARED_SHA256,
        "systemd_modified": False,
        "natural_observations_modified": False,
        "collector_activated": False,
        "primary_probe_thresholds_changed": False,
        "customer_data_accessed": False,
        "release_accepted": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
