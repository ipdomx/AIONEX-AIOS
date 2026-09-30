"""Offline checks for the locally revendored pip in a disposable image only.

All installation/resolution targets are temporary synthetic wheels. No external
index, production DB, real signing key or customer project is accessed. Actual
pip resolution, installation, both metadata backends, hashes and pip-audit's
requirement collection are exercised, not replaced by mocks.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


def run(args: list[str], env: dict[str, str], expected: int = 0) -> str:
    r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=90, check=False)
    if r.returncode != expected:
        raise RuntimeError(f"Offline pip operation failed ({r.returncode}): {r.stderr[-1500:]}")
    return r.stdout


def synthetic_wheel(root: Path, name: str, version: str, requires: str | None = None) -> Path:
    dist = name + "-" + version + ".dist-info/"
    metadata = "Metadata-Version: 2.1\nName: " + name + "\nVersion: " + version + "\n"
    if requires:
        metadata += "Requires-Dist: " + requires + "\n"
    payload = {
        name + "/__init__.py": ("value = " + repr(version) + "\n").encode(),
        dist + "METADATA": (metadata + "\n").encode(),
        dist + "WHEEL": b"Wheel-Version: 1.0\nGenerator: aionex-offline-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    rows = []
    for path, data in payload.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append((path, "sha256=" + digest, str(len(data))))
    rows.append((dist + "RECORD", "", ""))
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    payload[dist + "RECORD"] = stream.getvalue().encode()
    out = root / (name + "-" + version + "-py3-none-any.whl")
    with zipfile.ZipFile(out, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for path, data in payload.items():
            z.writestr(path, data)
    return out


def main() -> None:
    import importlib.metadata as md

    import pip
    from pip._vendor import msgpack, pkg_resources, requests
    from pip._vendor.cachecontrol.serialize import Serializer
    from pip._vendor.urllib3.response import HTTPResponse

    root = Path(pip.__file__).parent
    proof = json.loads((root / "_vendor/aios-provenance.json").read_text())
    outer = json.loads(Path("/usr/local/share/aionex/pip-vendor-provenance.json").read_text())
    assert pip.__version__ == md.version("pip") == proof["local_version"] == "26.2.1+aios.1"
    assert msgpack.__version__ == "1.2.3" and not proof["msgpack_compiled_extension_included"]
    assert not any((root / "_vendor/msgpack").glob("*.so"))
    assert not (root / "_vendor/setuptools").exists()
    for name, digest in proof["code_file_hashes"].items():
        assert hashlib.sha256((root.parent / name).read_bytes()).hexdigest() == digest
    for name, digest in outer["unchanged_pip_engine_files"].items():
        assert hashlib.sha256((root.parent / name).read_bytes()).hexdigest() == digest
    assert str(pkg_resources.Requirement.parse("fixture>=1,<2")) == "fixture<2,>=1"
    assert requests.Session().verify is True
    obj: dict[str, Any] = {"body": b"synthetic cache payload", "headers": {"x-test": "ok"}, "values": [None, True, 3, 4.5]}
    assert msgpack.unpackb(msgpack.packb(obj), raw=False) == obj
    req = requests.Request("GET", "https://offline.invalid/cache").prepare()
    response = HTTPResponse(body=io.BytesIO(b"synthetic cache payload"), status=200, preload_content=False, headers={"Content-Type": "text/plain"})
    serializer = Serializer()
    cache = serializer.dumps(req, response, body=b"synthetic cache payload")
    restored = serializer.loads(req, cache)
    assert restored is not None and restored.read() == b"synthetic cache payload"
    env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_CACHE_DIR": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    pip_cmd = [sys.executable, "-m", "pip"]
    assert "26.2.1+aios.1" in run(pip_cmd + ["--version"], env)
    assert "No broken requirements" in run(pip_cmd + ["check"], env)
    backends = []
    for backend in ("0", "1"):
        installed = json.loads(run(pip_cmd + ["list", "--format=json"], {**env, "_PIP_USE_IMPORTLIB_METADATA": backend}))
        assert next(x["version"] for x in installed if x["name"].lower() == "pip") == pip.__version__
        backends.append(backend)
    inspected = json.loads(run(pip_cmd + ["inspect"], env))
    assert inspected["installed"]
    debug = run(pip_cmd + ["debug"], env)
    assert "msgpack==1.2.3" in debug and "setuptools==80.9.0" in debug
    with tempfile.TemporaryDirectory(prefix="aios-pip-offline-") as folder:
        tmp = Path(folder)
        wheels = tmp / "wheels"
        wheels.mkdir()
        leaf = synthetic_wheel(wheels, "aios_vendor_leaf", "1.0")
        synthetic_wheel(wheels, "aios_vendor_leaf", "2.0")
        parent = synthetic_wheel(wheels, "aios_vendor_parent", "1.0", "aios_vendor_leaf==1.0")
        env["PIP_FIND_LINKS"] = str(wheels)
        requirements = tmp / "requirements.txt"
        requirements.write_text("aios_vendor_parent==1.0\n")
        report = tmp / "report.json"
        run(pip_cmd + ["install", "--dry-run", "--ignore-installed", "--report", str(report), "-r", str(requirements)], env)
        resolved = json.loads(report.read_text())
        assert {x["metadata"]["name"].replace("_", "-"): x["metadata"]["version"] for x in resolved["install"]} == {"aios-vendor-parent": "1.0", "aios-vendor-leaf": "1.0"}
        destination = tmp / "installed"
        run(pip_cmd + ["install", "--target", str(destination), "--no-compile", "aios_vendor_parent==1.0"], env)
        run([sys.executable, "-c", "import aios_vendor_leaf,aios_vendor_parent;assert aios_vendor_leaf.value==aios_vendor_parent.value=='1.0'"], {**env, "PYTHONPATH": str(destination)})
        for field in (parent, leaf):
            assert field.is_file()
        hashed = tmp / "hashed.txt"
        hashed.write_text("\n".join(p.stem.removesuffix("-py3-none-any").replace("-1.0", "==1.0") + " --hash=sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() for p in (parent, leaf)) + "\n")
        run(pip_cmd + ["install", "--dry-run", "--ignore-installed", "--require-hashes", "-r", str(hashed)], env)
        wrong = tmp / "wrong-hash.txt"
        wrong.write_text(hashed.read_text().replace(hashlib.sha256(parent.read_bytes()).hexdigest(), "0" * 64))
        r = subprocess.run(pip_cmd + ["install", "--dry-run", "--ignore-installed", "--require-hashes", "-r", str(wrong)], env=env, capture_output=True, text=True, timeout=45, check=False)
        assert r.returncode != 0 and "HASHES" in r.stderr
        r = subprocess.run(pip_cmd + ["install", "--dry-run", "--ignore-installed", "aios_vendor_parent==1.0", "aios_vendor_leaf==2.0"], env=env, capture_output=True, text=True, timeout=45, check=False)
        assert r.returncode != 0 and "ResolutionImpossible" in r.stderr
        audit = """import json,sys
from pathlib import Path
sys.path.insert(0,'/app/scripts')
from security_pip_audit import configure
cls=configure();assert cls([]).with_pip is False
from pip_audit._dependency_source import RequirementSource
items=list(RequirementSource([Path(sys.argv[1])]).collect())
print(json.dumps([{'name':x.name,'version':str(x.version)} for x in items]))
"""
        collected = json.loads(run([sys.executable, "-c", audit, str(requirements)], env))
        assert {x["name"].replace("_", "-"): x["version"] for x in collected} == {"aios-vendor-parent": "1.0", "aios-vendor-leaf": "1.0"}
        run(["/opt/venv/bin/pip-audit", "--dry-run", "-r", str(requirements)], env)
    print(json.dumps({
        "status": "PASS", "pip": pip.__version__, "vendor_msgpack": msgpack.__version__,
        "vendor_pkg_resources_from_setuptools": "80.9.0", "actual_vendor_code_files_verified": len(proof["code_file_hashes"]),
        "pip_engine_files_unchanged": len(outer["unchanged_pip_engine_files"]),
        "cachecontrol_native_roundtrip": True, "metadata_backends_exercised": backends,
        "pip_dependency_resolution_and_installation": True, "require_hashes_success_and_rejection": True,
        "dependency_conflict_rejected": True, "pip_audit_actual_requirement_collector": True, "pip_audit_cli_dry_run": True, "floating_bootstrap_installer_used": False,
        "external_network": False, "production_changed": False, "full_image_security_passed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
