"""Fail-closed liblzma package gate and bounded offline compatibility contracts."""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "web-dashboard/backend/scripts/verify_security_lzma.py"
spec = importlib.util.spec_from_file_location("fr06_security_lzma", SCRIPT)
assert spec and spec.loader
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.mark.parametrize("name", verifier.CASES)
def test_bounded_native_compatibility(name: str) -> None:
    assert verifier.native_case(name) == {"case": name, "passed": True}


def test_unknown_native_case_rejected() -> None:
    with pytest.raises(ValueError, match="Unrecognized"):
        verifier.native_case("arbitrary-input")


def test_rejection_gate_fails_when_decoder_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier.lzma, "decompress", lambda *_a, **_k: b"accepted")
    with pytest.raises(RuntimeError, match="accepted"):
        verifier.expect_rejection(b"synthetic")


@pytest.fixture
def package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    library = tmp_path / "liblzma.so.5"
    library.write_bytes(b"synthetic library metadata fixture, not a native library")
    state: dict[str, Any] = {"metadata": "liblzma5\t5.4.1-1+deb12u2\tamd64\tii ",
                             "query_rc": 0, "version_rc": 0, "verify_rc": 0, "verify_output": "",
                             "loaded": {library}, "commands": [], "library": library,
                             "control_rc": 0, "control_stderr": "", "verify_stderr": "",
                             "control": hashlib.md5(library.read_bytes(), usedforsecurity=False).hexdigest()
                             + "  " + library.relative_to("/").as_posix() + "\n"}

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        state["commands"].append(args)
        if args[:2] == ["dpkg-query", "--control-show"]:
            assert args == ["dpkg-query", "--control-show", "liblzma5:amd64", "md5sums"]
            return subprocess.CompletedProcess(args, state["control_rc"], state["control"], state["control_stderr"])
        if args[0] == "dpkg-query":
            return subprocess.CompletedProcess(args, state["query_rc"], state["metadata"], "")
        if args[1] == "--compare-versions":
            return subprocess.CompletedProcess(args, state["version_rc"], "", "")
        assert args == ["dpkg", "--verify", "liblzma5"]
        return subprocess.CompletedProcess(args, state["verify_rc"], state["verify_output"], state["verify_stderr"])

    monkeypatch.setattr(verifier, "LIBRARY", library)
    monkeypatch.setattr(verifier, "run", run)
    monkeypatch.setattr(verifier, "loaded_libraries", lambda: state["loaded"])
    return state


def test_package_metadata_hash_and_loaded_binding(package: dict[str, Any]) -> None:
    result = verifier.package_identity()
    assert result["version"] == "5.4.1-1+deb12u2"
    assert len(result["library_sha256"]) == 64
    assert ["dpkg", "--compare-versions", "5.4.1-1+deb12u2", "ge", "5.4.1-1+deb12u2"] in package["commands"]


@pytest.mark.parametrize("metadata", ["", "other\t5.4.1\tamd64\tii ",
    "liblzma5\t5.4.1\tarm64\tii ", "liblzma5\t5.4.1\tamd64\trc "])
def test_invalid_package_metadata_rejected(package: dict[str, Any], metadata: str) -> None:
    package["metadata"] = metadata
    with pytest.raises(RuntimeError, match="Installed official"):
        verifier.package_identity()


@pytest.mark.parametrize("field", ["query_rc", "version_rc", "verify_rc"])
def test_package_command_failures_rejected(package: dict[str, Any], field: str) -> None:
    package[field] = 1
    with pytest.raises(RuntimeError):
        verifier.package_identity()


def test_package_file_drift_rejected(package: dict[str, Any]) -> None:
    package["verify_output"] = "??5?????? /usr/lib/x86_64-linux-gnu/liblzma.so.5.4.1"
    with pytest.raises(RuntimeError, match="files differ"):
        verifier.package_identity()


@pytest.mark.parametrize("binding", [set(), {Path("/tmp/foreign-liblzma.so.5")}])
def test_wrong_loaded_library_rejected(package: dict[str, Any], binding: set[Path]) -> None:
    package["loaded"] = binding
    with pytest.raises(RuntimeError, match="exactly the verified"):
        verifier.package_identity()


def test_library_escape_rejected(package: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    actual = outside / "liblzma.so.5.4.1"
    actual.write_bytes(b"synthetic")
    link = tmp_path / "unexpected.so"
    link.symlink_to(actual)
    monkeypatch.setattr(verifier, "LIBRARY", link)
    with pytest.raises(RuntimeError, match="Unexpected native"):
        verifier.package_identity()


def test_runtime_installs_security_floor_without_scanner_exclusions() -> None:
    dockerfile = (ROOT / "web-dashboard/backend/Dockerfile.security-tools").read_text()
    runtime = dockerfile.split(" AS runtime\n", 1)[1]
    install = runtime.split("&& apt-get install -y --no-install-recommends", 1)[1].split("&&", 1)[0]
    assert "liblzma5" in install.split()
    assert "path-include=/usr/share/doc/liblzma5/*" in runtime
    assert "dpkg-query -W -f='${Version}' liblzma5" in runtime
    assert "ge '5.4.1-1+deb12u2'" in runtime
    assert runtime.index("ge '5.4.1-1+deb12u2'") < runtime.index("rm -rf /var/lib/apt/lists/*")
    assert runtime.index("USER 1000:1000") < runtime.index("RUN python /app/scripts/verify_security_lzma.py")
    assert "--allow-unauthenticated" not in runtime
    assert "--ignore-unfixed" not in runtime


@pytest.mark.parametrize("mode", ["empty", "whitespace", "malformed", "non-hex", "short-digest",
                                  "missing-native", "duplicate-native", "absolute-path", "traversal",
                                  "noncanonical", "backslash", "nul", "oversized", "wrong-digest"])
def test_native_manifest_does_not_accept_incomplete_integrity(package: dict[str, Any], mode: str) -> None:
    original = package["control"]
    digest, name = original.rstrip("\n").split("  ", 1)
    variants = {
        "empty": "", "whitespace": "  \n", "malformed": "not-a-checksum\n",
        "non-hex": "z" * 32 + "  " + name + "\n",
        "short-digest": digest[:-1] + "  " + name + "\n",
        "missing-native": digest + "  usr/share/doc/liblzma5/copyright\n",
        "duplicate-native": original + original,
        "absolute-path": digest + "  /" + name + "\n",
        "traversal": digest + "  ../" + name + "\n",
        "noncanonical": digest + "  ./" + name + "\n",
        "backslash": digest + "  bad\\path\n",
        "nul": digest + "  bad\x00path\n",
        "oversized": "x" * (1024 * 1024 + 1),
        "wrong-digest": "0" * 32 + "  " + name + "\n",
    }
    package["control"] = variants[mode]
    with pytest.raises(RuntimeError, match="checksum"):
        verifier.package_identity()


@pytest.mark.parametrize("field,value", [("control_rc", 2), ("control_stderr", "metadata warning"),
                                          ("verify_stderr", "files list missing")])
def test_native_metadata_command_ambiguity_rejected(package: dict[str, Any], field: str, value: Any) -> None:
    package[field] = value
    with pytest.raises(RuntimeError):
        verifier.package_identity()


def test_native_bytes_compared_even_when_dpkg_returns_empty_success(package: dict[str, Any]) -> None:
    package["library"].write_bytes(b"changed synthetic native file")
    with pytest.raises(RuntimeError, match="content checksum differs"):
        verifier.package_identity()


def test_native_manifest_keeps_package_checksum_and_sha256(package: dict[str, Any]) -> None:
    result = verifier.package_identity()
    assert result["library_package_md5"] == package["control"].split("  ", 1)[0]
    assert result["library_sha256"] == hashlib.sha256(package["library"].read_bytes()).hexdigest()
    assert ["dpkg", "--verify", "liblzma5"] in package["commands"]
