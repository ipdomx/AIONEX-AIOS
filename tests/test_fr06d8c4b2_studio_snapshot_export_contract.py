"""Source boundaries for the Studio drain snapshot exporters."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend/app/services/studio_drain_input_export.py"
HOST = ROOT / "scripts/security/fr06d8c4_studio_snapshot_export.py"


def _calls(path: Path):
    tree = ast.parse(path.read_text())
    return [
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]


def test_backend_exporter_has_no_database_or_filesystem_mutation_calls():
    calls = _calls(BACKEND)
    forbidden = (
        ".commit", ".rollback", ".add", ".delete", ".unlink", ".remove",
        ".replace", ".rename", ".write_text", ".write_bytes",
    )
    assert not any(call.endswith(forbidden) for call in calls)


def test_backend_exporter_sandwiches_studio_and_backup_with_authority_reads():
    text = BACKEND.read_text()
    assert text.count("read_admission_snapshot") >= 3
    assert "execution_snapshot" in text
    assert "snapshot_backup_cycles" in text
    assert "maintenance authority changed during snapshot collection" in text


def test_host_collector_has_no_container_control_or_studio_mutation_commands():
    text = HOST.read_text().lower()
    for forbidden in (
        "docker stop", "docker restart", "docker compose", "unlink(",
        "rename(", "replace(", "close_admission", "open_admission",
    ):
        assert forbidden not in text
    assert '"docker", "exec"' in HOST.read_text()


def test_host_output_is_create_only_private():
    text = HOST.read_text()
    assert "os.O_EXCL" in text
    assert "0o600" in text
