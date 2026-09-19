"""Source boundaries for FR-06D8C4B Studio writer epoch."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_writer_epoch.py"


def _node(name):
    tree = ast.parse(SCRIPT.read_text())
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _calls(node):
    return [
        ast.unparse(item.func)
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
    ]


def test_evaluate_has_no_host_or_filesystem_mutation_calls():
    calls = _calls(_node("evaluate"))
    forbidden = (
        ".unlink",
        ".remove",
        ".replace",
        ".rename",
        ".link",
        ".symlink",
        ".mkdir",
        ".write_text",
        ".write_bytes",
        "subprocess.run",
    )
    assert not any(call.endswith(forbidden) for call in calls)


def test_receipt_explicitly_denies_cleanup_and_full_drain_claims():
    source = SCRIPT.read_text()
    for marker in (
        '"process_drain_verified": False',
        '"host_process_scan_verified": False',
        '"backup_cycle_drain_verified": False',
        '"cleanup_authorized": False',
        '"filesystem_mutation_performed": False',
        '"full_host_closure": False',
    ):
        assert marker in source


def test_writer_scope_is_backend_and_studio_worker_only():
    source = SCRIPT.read_text()
    assert 'WRITERS = frozenset({"backend", "studio-worker"})' in source
    assert 'READERS = frozenset({"backup-worker"})' in source
    assert 'DESTINATION = "/var/lib/aionex/studio-assets"' in source


def test_cli_does_not_stop_restart_or_mutate_admission():
    calls = _calls(_node("main"))
    text = " ".join(calls).lower()
    for forbidden in (
        "docker.stop",
        "docker.restart",
        "docker.compose",
        "close_admission",
        "open_admission",
    ):
        assert forbidden not in text


def test_compose_writer_reader_scope_matches_runtime_contract():
    compose = (ROOT / "web-dashboard/docker-compose.production.yml").read_text()
    blocks = {}
    current = None
    lines = []
    for line in compose.splitlines():
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            if current is not None:
                blocks[current] = "\n".join(lines)
            current = line.strip()[:-1]
            lines = []
            continue
        if current is not None:
            lines.append(line)
    if current is not None:
        blocks[current] = "\n".join(lines)

    needle = "studio_asset_data:/var/lib/aionex/studio-assets:"
    mounted = {
        service: block
        for service, block in blocks.items()
        if needle in block
    }
    assert set(mounted) == {
        "backend",
        "backup-asset-root-init",
        "backup-worker",
        "studio-worker",
    }
    assert needle + "rw" in mounted["backend"]
    assert needle + "rw" in mounted["studio-worker"]
    assert needle + "ro" in mounted["backup-worker"]
    assert needle + "rw" in mounted["backup-asset-root-init"]
    assert 'restart: "no"' in mounted["backup-asset-root-init"]
