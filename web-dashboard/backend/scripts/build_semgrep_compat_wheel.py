"""Build an explicitly locally-versioned Semgrep compatibility wheel.

The pinned upstream wheel requires PyJWT ~=2.13.0, conflicting with the fixed
2.14.0 runtime. Only its dependency metadata and local version are changed;
every executable, rule and Python module remains byte-identical to upstream.
A full input RECORD/hash check precedes output. No dependency checks are disabled.
This helper builds files only: it never installs packages or touches services.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import stat
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

UPSTREAM_VERSION = "1.178.0"
LOCAL_VERSION = "1.178.0+aios.1"
UPSTREAM_NAME = "semgrep-1.178.0-cp310.cp311.cp312.cp313.cp314.py310.py311.py312.py313.py314-none-manylinux_2_34_x86_64.whl"
UPSTREAM_URL = "https://files.pythonhosted.org/packages/b3/bf/5bc9cc1b1e1650467ceb6361306d170dd3641b911efa2a89bc7129be4d54/" + UPSTREAM_NAME
UPSTREAM_SHA256 = "b7c4a4ba5cad1a6b0e76f7143c164b3f2853b9d0f902f2db2f64006257c941f2"
OLD_DIST = "semgrep-1.178.0.dist-info/"
NEW_DIST = "semgrep-1.178.0+aios.1.dist-info/"
OLD_REQUIREMENT = "Requires-Dist: pyjwt[crypto]~=2.13.0\n"
NEW_REQUIREMENT = "Requires-Dist: pyjwt[crypto]>=2.14.0,<2.15.0\n"
MAX_ARCHIVE = 100 * 1024**2
MAX_EXPANDED = 512 * 1024**2


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def rewrite_wheel(source: Path, output: Path, *, expected_sha256: str = UPSTREAM_SHA256) -> dict[str, object]:
    """Verify then emit a derived wheel; expected_sha256 is injectable for unit fixtures."""
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_ARCHIVE:
        raise ValueError("Unsafe or oversized upstream wheel")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Expected SHA256 required")
    raw = source.read_bytes()
    if digest(raw) != expected_sha256:
        raise ValueError("Upstream wheel SHA256 mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or sum(item.file_size for item in infos) > MAX_EXPANDED:
            raise ValueError("Duplicate members or expanded size exceeded")
        for item in infos:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or item.is_dir():
                raise ValueError("Non-file or unsafe archive member")
            if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                raise ValueError("Symlink or encrypted member rejected")
        metadata_name, record_name = OLD_DIST + "METADATA", OLD_DIST + "RECORD"
        if {n for n in names if n.endswith(".dist-info/METADATA")} != {metadata_name}:
            raise ValueError("Unexpected distribution identity")
        if any(n.endswith(("RECORD.jws", "RECORD.p7s")) for n in names):
            raise ValueError("Signed input cannot be silently repackaged")
        table: dict[str, tuple[str, str]] = {}
        for row in csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))):
            if len(row) != 3 or row[0] in table:
                raise ValueError("Invalid upstream RECORD")
            table[row[0]] = (row[1], row[2])
        if set(table) != set(names) or table[record_name] != ("", ""):
            raise ValueError("RECORD coverage differs")
        for name in names:
            if name != record_name:
                value = archive.read(name)
                if table[name] != (record_hash(value), str(len(value))):
                    raise ValueError("Upstream RECORD hash or size mismatch")
        metadata = archive.read(metadata_name).decode("utf-8")
        for line in ("Name: semgrep\n", "Version: 1.178.0\n", OLD_REQUIREMENT, "Requires-Dist: mcp==1.29.0\n"):
            if metadata.count(line) != 1:
                raise ValueError("Upstream dependency metadata changed")
        patched = metadata.replace("Version: 1.178.0\n", "Version: " + LOCAL_VERSION + "\n").replace(OLD_REQUIREMENT, NEW_REQUIREMENT).encode("utf-8")
        output.mkdir(parents=True, exist_ok=True)
        if output.is_symlink():
            raise ValueError("Output directory must not be a symlink")
        target = output / UPSTREAM_NAME.replace(UPSTREAM_VERSION, LOCAL_VERSION, 1)
        payload: dict[str, str] = {}
        rows: list[tuple[str, str, str]] = []
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as result:
            for item in infos:
                if item.filename == record_name:
                    continue
                data = patched if item.filename == metadata_name else archive.read(item.filename)
                name = item.filename.replace(OLD_DIST, NEW_DIST, 1) if item.filename.startswith(OLD_DIST) else item.filename
                copied = zipfile.ZipInfo(name, item.date_time)
                copied.compress_type = zipfile.ZIP_DEFLATED
                copied.external_attr = item.external_attr
                copied.create_system = item.create_system
                result.writestr(copied, data)
                rows.append((name, record_hash(data), str(len(data))))
                if not item.filename.startswith(OLD_DIST):
                    payload[name] = digest(data)
            rows.append((NEW_DIST + "RECORD", "", ""))
            buffer = io.StringIO(newline="")
            csv.writer(buffer, lineterminator="\n").writerows(rows)
            info = zipfile.ZipInfo(NEW_DIST + "RECORD", (2026, 9, 23, 0, 0, 0))
            result.writestr(info, buffer.getvalue().encode())
    with zipfile.ZipFile(target) as result:
        if any(digest(result.read(name)) != expected for name, expected in payload.items()):
            raise ValueError("Executable payload changed during rewrite")
    proof: dict[str, object] = {
        "upstream_version": UPSTREAM_VERSION, "local_version": LOCAL_VERSION,
        "upstream_sha256": expected_sha256, "derived_wheel": target.name,
        "derived_sha256": digest(target.read_bytes()), "payload_files_unchanged": payload,
        "only_metadata_changed": True, "dependency_checks_disabled": False,
        "old_requirement": OLD_REQUIREMENT.strip(), "new_requirement": NEW_REQUIREMENT.strip(),
    }
    with (output / "semgrep-compat-provenance.json").open("x") as stream:
        json.dump(proof, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source
    if source is None:
        args.output.mkdir(parents=True, exist_ok=True)
        source = args.output / UPSTREAM_NAME
        # Public immutable PyPI artifact only; do not fetch a floating version.
        with urllib.request.urlopen(UPSTREAM_URL, timeout=120) as response, source.open("xb") as stream:
            total = 0
            while chunk := response.read(1024**2):
                total += len(chunk)
                if total > MAX_ARCHIVE:
                    raise ValueError("Download exceeded fixed bound")
                stream.write(chunk)
    proof = rewrite_wheel(source, args.output)
    print(json.dumps({k: v for k, v in proof.items() if k != "payload_files_unchanged"}, sort_keys=True))


if __name__ == "__main__":
    main()
