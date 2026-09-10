"""Source-only regression gate for the existing production backend build contract.

No Docker daemon, network, environment files, credentials, or production data are
accessed. These checks cover this repository's explicit block-style Compose file;
they are not a general YAML parser or a substitute for real image acceptance.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "web-dashboard/docker-compose.production.yml"
DOCKERFILE = ROOT / "web-dashboard/backend/Dockerfile"
IMAGE = "aionex-aios-backend:local"
TARGET = "project-worker"
BUILDERS = ("backend", "postgres-credential-reconciler")


def service_blocks(text: str) -> dict[str, str]:
    """Read this file's literal, two-space service blocks; reject duplicates."""
    roots = list(re.finditer(r"(?m)^services:\s*$", text))
    assert len(roots) == 1, "Exactly one services mapping is required"
    tail = text[roots[0].end():]
    end = re.search(r"(?m)^[A-Za-z_][\w-]*:", tail)
    body = tail[:end.start()] if end else tail
    starts = list(re.finditer(r"(?m)^  ([A-Za-z_][\w-]*):\s*$", body))
    names = [match.group(1) for match in starts]
    assert len(names) == len(set(names)), "Duplicate service definitions"
    return {
        match.group(1): body[match.end():starts[i + 1].start() if i + 1 < len(starts) else len(body)]
        for i, match in enumerate(starts)
    }


def build_block(service: str) -> str:
    matches = list(re.finditer(r"(?m)^    build:\s*$", service))
    assert len(matches) == 1, "An explicit build mapping is required"
    tail = service[matches[0].end():]
    end = re.search(r"(?m)^    [A-Za-z_][\w-]*:", tail)
    return tail[:end.start()] if end else tail


def assert_contract(compose: str, dockerfile: str) -> None:
    services = service_blocks(compose)
    assert all(name in services for name in BUILDERS), "Shared image builder is missing"
    shared_builders = []
    for name, block in services.items():
        image = re.findall(r"(?m)^    image: ([^\n]+)$", block)
        if image == [IMAGE] and re.search(r"(?m)^    build:", block):
            shared_builders.append(name)
            build = build_block(block)
            assert re.findall(r"(?m)^      target: ([^\n]+)$", build) == [TARGET], "Explicit project-worker target required"
            assert re.findall(r"(?m)^      context: ([^\n]+)$", build) == ["./backend"]
            assert re.findall(r"(?m)^      dockerfile: ([^\n]+)$", build) == ["Dockerfile"]
    assert set(BUILDERS) <= set(shared_builders), "Shared image tag or build definition changed"
    headers = list(re.finditer(r"(?im)^FROM\s+(\S+)\s+AS\s+([\w-]+)\s*$", dockerfile))
    selected = [(i, match) for i, match in enumerate(headers) if match.group(2) == TARGET]
    assert len(selected) == 1, "Selected Dockerfile stage is missing or ambiguous"
    i, match = selected[0]
    assert match.group(1) == "runtime", "Project worker must inherit the runtime stage"
    body = dockerfile[match.end():headers[i + 1].start() if i + 1 < len(headers) else len(dockerfile)]
    body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    assert "COPY --from=project-worker-builder /opt/venv /opt/venv" in body
    package_line = next((line for line in body.splitlines() if "apk add --no-cache" in line), "")
    for executable in ("nodejs", "npm", "chromium", "chromium-chromedriver"):
        assert executable in package_line.replace(";", " ").split(), "Existing project toolchain must be retained"


def mutate_build(compose: str, service: str, replacement: str) -> str:
    block = service_blocks(compose)[service]
    assert "      target: project-worker\n" in block
    changed = block.replace("      target: project-worker\n", replacement, 1)
    return compose.replace(block, changed, 1)


def test_production_shared_image_has_explicit_compatible_targets():
    assert_contract(COMPOSE.read_text(), DOCKERFILE.read_text())


@pytest.mark.parametrize("service", BUILDERS)
@pytest.mark.parametrize("replacement", ["", "      target: runtime\n", "      target: test\n"])
def test_reject_missing_or_incompatible_target(service, replacement):
    with pytest.raises(AssertionError, match="Explicit project-worker"):
        assert_contract(mutate_build(COMPOSE.read_text(), service, replacement), DOCKERFILE.read_text())


def test_reject_implicit_pre_fix_contract():
    original = COMPOSE.read_text().replace("      target: project-worker\n", "")
    with pytest.raises(AssertionError, match="Explicit project-worker"):
        assert_contract(original, DOCKERFILE.read_text())


def test_unrelated_later_docker_stage_does_not_change_selected_target():
    dockerfile = DOCKERFILE.read_text() + "\nFROM runtime AS unrelated-later-stage\n"
    assert_contract(COMPOSE.read_text(), dockerfile)


def test_reject_missing_selected_stage():
    dockerfile = DOCKERFILE.read_text().replace("FROM runtime AS project-worker\n", "FROM runtime AS renamed-stage\n")
    with pytest.raises(AssertionError, match="stage is missing"):
        assert_contract(COMPOSE.read_text(), dockerfile)


@pytest.mark.parametrize("executable", ["nodejs", "npm", "chromium", "chromium-chromedriver"])
def test_reject_loss_of_existing_project_tool(executable):
    dockerfile = DOCKERFILE.read_text()
    prefix, stage = dockerfile.split("FROM runtime AS project-worker\n", 1)
    stage = re.sub(r"(?<![\w-])" + re.escape(executable) + r"(?![\w-])", "removed-tool", stage)
    with pytest.raises(AssertionError, match="toolchain must be retained"):
        assert_contract(COMPOSE.read_text(), prefix + "FROM runtime AS project-worker\n" + stage)


def test_reject_loss_of_project_python_environment():
    dockerfile = DOCKERFILE.read_text().replace("COPY --from=project-worker-builder /opt/venv /opt/venv", "# removed copy")
    with pytest.raises(AssertionError):
        assert_contract(COMPOSE.read_text(), dockerfile)


def test_reject_duplicate_target_configuration():
    compose = mutate_build(COMPOSE.read_text(), "backend", "      target: project-worker\n      target: runtime\n")
    with pytest.raises(AssertionError, match="Explicit project-worker"):
        assert_contract(compose, DOCKERFILE.read_text())
