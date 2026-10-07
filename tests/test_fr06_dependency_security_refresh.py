"""Source contracts for 2026-10-01 alerts 39/40/43, without provider I/O.

These checks do not prove GPU image rebuild, deployment, protected CI or closure
of GitHub alerts. Keep the source remediation distinct from runtime acceptance.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRIPOSR = ROOT / "infra/runpod/triposr"
VIP = ROOT / "vip-frontend"


def version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    assert match is not None, "Require an exact stable version, not an ambiguous range"
    return tuple(int(piece) for piece in match.groups())


@pytest.mark.parametrize("filename", ["requirements.txt", "security-overrides.txt"])
def test_all_triposr_urllib3_pins_include_proxy_and_chunk_fixes(filename: str) -> None:
    lines = (TRIPOSR / filename).read_text().splitlines()
    values = [line.split("==", 1)[1] for line in lines if line.startswith("urllib3==")]
    assert len(values) == 1
    assert (2, 8, 0) <= version(values[0]) < (3, 0, 0)


def test_triposr_constraints_and_install_requirements_agree() -> None:
    def pins(filename: str) -> dict[str, str]:
        return dict(line.split("==", 1) for line in (TRIPOSR / filename).read_text().splitlines() if "==" in line)
    requirements, constraints = pins("requirements.txt"), pins("security-overrides.txt")
    assert requirements["urllib3"] == constraints["urllib3"]


def test_grpc_override_uses_patched_compatible_minor() -> None:
    manifest = json.loads((VIP / "package.json").read_text())
    assert manifest["overrides"]["@grpc/grpc-js"] == "1.13.6"


def test_every_grpc_lock_instance_is_patched_and_matches_override() -> None:
    manifest = json.loads((VIP / "package.json").read_text())
    lock = json.loads((VIP / "package-lock.json").read_text())
    nodes = {name: value for name, value in lock["packages"].items() if name.endswith("node_modules/@grpc/grpc-js")}
    assert nodes, "The relevant transitive dependency must not disappear from inspection"
    for name, node in nodes.items():
        resolved = version(node["version"])
        assert resolved >= (1, 13, 6) and not (1, 14, 0) <= resolved < (1, 14, 5), name
        assert node["version"] == manifest["overrides"]["@grpc/grpc-js"]
        assert node["resolved"] == f'https://registry.npmjs.org/@grpc/grpc-js/-/grpc-js-{node["version"]}.tgz'
        assert node["integrity"].startswith("sha512-")


def test_no_unrelated_direct_frontend_dependency_upgrade() -> None:
    manifest = json.loads((VIP / "package.json").read_text())
    assert manifest["dependencies"]["firebase"] == "12.16.0"
    assert manifest["dependencies"]["next"] == "15.5.24"
    assert manifest["dependencies"]["react"] == "18.3.1"
    assert manifest["overrides"]["sharp"] == "0.35.5"


def test_existing_gpu_install_compatibility_checks_retained() -> None:
    dockerfile = (TRIPOSR / "Dockerfile").read_text()
    assert "python -m pip check" in dockerfile
    assert "from transformers.models.vit.modeling_vit import ViTModel" in dockerfile


@pytest.mark.parametrize("path,patched", [
    ("node_modules/brace-expansion", "1.1.21"),
    ("node_modules/@typescript-eslint/typescript-estree/node_modules/brace-expansion", "5.0.12"),
])
def test_brace_expansion_lock_instances_include_all_new_fixes(path: str, patched: str) -> None:
    lock = json.loads((VIP / "package-lock.json").read_text())
    node = lock["packages"][path]
    assert node["version"] == patched
    assert node["integrity"].startswith("sha512-")
    assert node["resolved"] == f"https://registry.npmjs.org/brace-expansion/-/brace-expansion-{patched}.tgz"
