"""Build the explicitly local pip 26.2.1+aios.1 vendored-library refresh.

Replace real msgpack Python code and pkg_resources code from hash-pinned PyPI
wheels; do not relabel old code, suppress findings, or remove pip-audit. The pip
engine and all other vendored libraries are unchanged. Only the import adapters
needed for pip's existing vendoring layout are applied to pkg_resources. Licenses,
RECORD, vendor.txt, CycloneDX references and the local version stay consistent.
No installation, service operation, or arbitrary shell command occurs here.
"""
from __future__ import annotations

import argparse
import base64
import csv
import difflib
import hashlib
import io
import json
import re
import stat
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "26.2.1+aios.1"
OLD_DIST = "pip-26.2.1.dist-info/"
NEW_DIST = "pip-" + VERSION + ".dist-info/"
MAX_INPUT = 20 * 1024**2
MAX_EXPANDED = 100 * 1024**2
INPUTS = {
    "pip": ("pip-26.2.1-py3-none-any.whl", "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e", "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl"),
    "setuptools": ("setuptools-80.9.0-py3-none-any.whl", "062d34222ad13e0cc312a4c02d73f059e86a4acbfbdea8f8f76b28c99f306922", "https://files.pythonhosted.org/packages/a3/dc/17031897dae0efacfea57dfd3a82fdd2a2aeb58e0ff71b77b87e44edc772/setuptools-80.9.0-py3-none-any.whl"),
    "msgpack": ("msgpack-1.2.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl", "382b219de3d436de3baba0f4b0c6d4336e8f5858d0eb047918b13b69a71c6c55", "https://files.pythonhosted.org/packages/aa/83/800570e6a22376eb8d599920f70aead4779a63611696f567477c4e85a70f/msgpack-1.2.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl"),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def verified_wheel(path: Path, digest: str) -> dict[str, bytes]:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Expected SHA256 required")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT:
        raise ValueError("Unsafe wheel input")
    raw = path.read_bytes()
    if sha(raw) != digest:
        raise ValueError("Wheel SHA256 mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = z.infolist()
        if len(infos) > 20000 or len({x.filename for x in infos}) != len(infos):
            raise ValueError("Duplicate members or excessive entry count")
        if sum(x.file_size for x in infos) > MAX_EXPANDED:
            raise ValueError("Expanded wheel exceeds limit")
        files = {}
        for x in infos:
            name = x.filename
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name or str(p) != name.rstrip("/"):
                raise ValueError("Unsafe or noncanonical wheel member")
            if stat.S_ISLNK(x.external_attr >> 16) or x.flag_bits & 1:
                raise ValueError("Symlink or encrypted wheel member")
            if x.is_dir():
                if x.file_size:
                    raise ValueError("Nonempty archive directory")
                continue
            if name.endswith(("RECORD.jws", "RECORD.p7s")):
                raise ValueError("Signed wheel cannot be silently repackaged")
            files[name] = z.read(name)
    records = [x for x in files if x.endswith(".dist-info/RECORD")]
    # Dependency wheels may themselves include vendor dist-info records.
    records = [x for x in records if len(PurePosixPath(x).parts) == 2]
    if len(records) != 1:
        raise ValueError("Ambiguous wheel RECORD")
    record = records[0]
    table: dict[str, tuple[str, str]] = {}
    for row in csv.reader(io.StringIO(files[record].decode("utf-8"))):
        if len(row) != 3 or row[0] in table:
            raise ValueError("Malformed RECORD")
        table[row[0]] = (row[1], row[2])
    if set(table) != set(files) or table[record] != ("", ""):
        raise ValueError("RECORD coverage differs")
    for name, data in files.items():
        if name != record and table[name] != (record_hash(data), str(len(data))):
            raise ValueError("RECORD integrity failure")
    return files


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("Pinned source text drifted")
    return text.replace(old, new)


def adapt_resources(raw: bytes) -> bytes:
    """Only dependency namespace/path adapters, not package selection logic."""
    text = raw.decode("utf-8")
    path_line = "sys.path.extend(((vendor_path := os.path.join(os.path.dirname(os.path.dirname(__file__)), 'setuptools', '_vendor')) not in sys.path) * [vendor_path])  # fmt: skip\n"
    text = replace_once(text, path_line, "# AIONEX: use pip's existing vendored dependencies, not setuptools/_vendor.\n")
    text = replace_once(text, "# workaround for #4476\nsys.modules.pop('backports', None)\n", "")
    for module in ("markers", "requirements", "specifiers", "utils", "version"):
        text = replace_once(text, "import packaging." + module + "\n", "IMPORT_" + module + "\n")
        text = text.replace("packaging." + module, "_packaging_" + module)
        text = text.replace("IMPORT_" + module, "from pip._vendor.packaging import " + module + " as _packaging_" + module)
    text = replace_once(text, "from jaraco.text import drop_comment, join_continuation, yield_lines", "from pip._internal.utils._jaraco_text import drop_comment, join_continuation, yield_lines")
    text = replace_once(text, "from platformdirs import user_cache_dir as _user_cache_dir", "from pip._vendor.platformdirs import user_cache_dir as _user_cache_dir")
    compile(text, "pkg_resources-vendored", "exec")
    return text.encode()


def build(inputs: Path, output: Path) -> dict[str, Any]:
    wheels = {key: verified_wheel(inputs / value[0], value[1]) for key, value in INPUTS.items()}
    original = wheels["pip"]
    files = dict(original)
    files.pop(OLD_DIST + "RECORD")
    files[OLD_DIST + "METADATA"] = replace_once(files[OLD_DIST + "METADATA"].decode(), "Version: 26.2.1\n", "Version: " + VERSION + "\n").encode()
    files["pip/__init__.py"] = replace_once(files["pip/__init__.py"].decode(), '__version__ = "26.2.1"', '__version__ = "' + VERSION + '"').encode()
    changed_code: dict[str, str] = {}
    for name in ("__init__.py", "exceptions.py", "ext.py", "fallback.py"):
        data = wheels["msgpack"]["msgpack/" + name]
        target = "pip/_vendor/msgpack/" + name
        files[target] = data
        changed_code[target] = sha(data)
    raw_resources = wheels["setuptools"]["pkg_resources/__init__.py"]
    resource_name = "pip/_vendor/pkg_resources/__init__.py"
    files[resource_name] = adapt_resources(raw_resources)
    changed_code[resource_name] = sha(files[resource_name])
    for target, key, source in (
        ("msgpack/COPYING", "msgpack", "msgpack-1.2.3.dist-info/licenses/COPYING"),
        ("pkg_resources/LICENSE", "setuptools", "setuptools-80.9.0.dist-info/licenses/LICENSE"),
    ):
        data = wheels[key][source]
        files["pip/_vendor/" + target] = data
        files[OLD_DIST + "licenses/src/pip/_vendor/" + target] = data
    vendor = files["pip/_vendor/vendor.txt"].decode()
    for old, new in (("msgpack==1.1.2", "msgpack==1.2.3"), ("setuptools==70.3.0", "setuptools==80.9.0")):
        vendor = replace_once(vendor, old, new)
    files["pip/_vendor/vendor.txt"] = vendor.encode()
    bom = json.loads(files["pip/_vendor/bom.cdx.json"])
    for name, old, new in (("msgpack", "1.1.2", "1.2.3"), ("setuptools", "70.3.0", "80.9.0")):
        components = [c for c in bom["components"] if c["name"] == name]
        if len(components) != 1 or components[0]["version"] != old:
            raise ValueError("Upstream SBOM identity drifted")
        component = components[0]
        before, after = "pkg:pypi/" + name + "@" + old, "pkg:pypi/" + name + "@" + new
        if component["bom-ref"] != before or component["purl"] != before:
            raise ValueError("Upstream SBOM reference drifted")
        component.update({"version": new, "bom-ref": after, "purl": after})
        for dependency in bom["dependencies"]:
            if dependency["ref"] == before:
                dependency["ref"] = after
            if "dependsOn" in dependency:
                dependency["dependsOn"] = [after if x == before else x for x in dependency["dependsOn"]]
    bom["metadata"]["component"]["version"] = VERSION
    bom["metadata"]["component"]["purl"] = "pkg:pypi/pip@" + VERSION.replace("+", "%2B")
    files["pip/_vendor/bom.cdx.json"] = (json.dumps(bom, indent=2, sort_keys=True) + "\n").encode()
    patch = "".join(difflib.unified_diff(raw_resources.decode().splitlines(keepends=True), files[resource_name].decode().splitlines(keepends=True), fromfile="setuptools-80.9.0/pkg_resources/__init__.py", tofile=resource_name))
    files["pip/_vendor/aios-pkg-resources.patch"] = patch.encode()
    files["pip/_vendor/README.rst"] += b"\nAIONEX local vendoring refresh\n=============================\nThis is pip 26.2.1+aios.1, not an upstream pip release.\nmsgpack 1.2.3 Python-only payload replaces msgpack 1.1.2.\npkg_resources comes from setuptools 80.9.0; only pip namespace adapters\nare applied (aios-pkg-resources.patch). No setuptools package_index code\nis added. Other pip engine/library code and TLS checks remain unchanged.\n"
    proof: dict[str, Any] = {
        "local_version": VERSION, "upstream_pip_version": "26.2.1",
        "inputs": {k: {"filename": v[0], "sha256": v[1], "url": v[2]} for k, v in INPUTS.items()},
        "code_file_hashes": changed_code,
        "pkg_resources_upstream_sha256": sha(raw_resources),
        "import_adapter_patch_sha256": sha(patch.encode()),
        "msgpack_compiled_extension_included": False,
        "pkg_resources_scope": "pkg_resources only; no setuptools/package_index.py",
        "scan_suppressions": [],
    }
    files["pip/_vendor/aios-provenance.json"] = (json.dumps(proof, indent=2, sort_keys=True) + "\n").encode()
    files = {name.replace(OLD_DIST, NEW_DIST, 1) if name.startswith(OLD_DIST) else name: data for name, data in files.items()}
    unchanged_engine = {n: sha(v) for n, v in original.items() if n.startswith("pip/_internal/")}
    if any(sha(files[n]) != digest for n, digest in unchanged_engine.items()):
        raise ValueError("pip engine unexpectedly changed")
    if output.is_symlink() or output.exists():
        raise FileExistsError("New output directory required")
    output.mkdir(mode=0o755, parents=True)
    wheel_target = output / ("pip-" + VERSION + "-py3-none-any.whl")
    rows = [(n, record_hash(v), str(len(v))) for n, v in sorted(files.items())]
    rows.append((NEW_DIST + "RECORD", "", ""))
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    files[NEW_DIST + "RECORD"] = buffer.getvalue().encode()
    with zipfile.ZipFile(wheel_target, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 9, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.create_system = 3
            z.writestr(info, data)
    if verified_wheel(wheel_target, sha(wheel_target.read_bytes())) != files:
        raise ValueError("Derived wheel verification failed")
    result = {**proof, "wheel": wheel_target.name, "sha256": sha(wheel_target.read_bytes()), "unchanged_pip_engine_files": unchanged_engine, "files": len(files)}
    (output / "pip-vendor-provenance.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        args.inputs.mkdir(mode=0o755, parents=True, exist_ok=False)
        for filename, digest, url in INPUTS.values():
            with urllib.request.urlopen(url, timeout=90) as response, (args.inputs / filename).open("xb") as stream:
                count = 0
                while chunk := response.read(1024**2):
                    count += len(chunk)
                    if count > MAX_INPUT:
                        raise ValueError("Wheel download exceeds bound")
                    stream.write(chunk)
            verified_wheel(args.inputs / filename, digest)
    proof = build(args.inputs, args.output)
    print(json.dumps({k: v for k, v in proof.items() if k not in {"unchanged_pip_engine_files", "code_file_hashes"}}, sort_keys=True))


if __name__ == "__main__":
    main()
