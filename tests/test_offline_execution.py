import hashlib
import json
import socket
from pathlib import Path

import pytest

from aios.offline_execution import OfflineMockExecutor


PROVIDER_KEY_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "OLLAMA_HOST",
)


def test_offline_execution_creates_complete_approved_cycle(tmp_path, monkeypatch):
    for name in PROVIDER_KEY_NAMES:
        monkeypatch.setenv(name, "must-not-be-read")

    def blocked_socket(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    root = tmp_path / "output"
    result = OfflineMockExecutor().execute(
        execution_id="cycle-001",
        project="AIONEX-AIOS",
        objective="Validate deterministic offline execution",
        output_root=root,
    )

    assert result.approved is True
    assert result.readiness_score == 1.0
    assert result.blocking_findings == ()
    assert result.rework_plan == ()
    assert result.network_used is False
    assert result.provider_keys_used is False
    assert result.production_modified is False
    assert len(result.artifact_paths) == 6
    assert all(path.is_file() for path in result.artifact_paths)
    assert result.manifest_path.is_file()
    assert result.report_path.is_file()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["departments"] == [
        "Architecture",
        "Backend",
        "Frontend",
        "Security",
        "Quality",
        "DevOps",
    ]
    assert manifest["review"] == {
        "approved": True,
        "readiness_score": 1.0,
        "blocking_findings": [],
        "rework_plan": [],
    }
    assert manifest["proof"] == {
        "network_used": False,
        "provider_keys_used": False,
        "production_modified": False,
    }
    assert len(manifest["artifacts"]) == 6

    for record in manifest["artifacts"]:
        artifact = result.output_directory / record["path"]
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert digest == record["sha256"]
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["department"] == record["department"]
        assert payload["execution"]["network_used"] is False
        assert payload["execution"]["provider_keys_used"] is False
        assert payload["execution"]["production_modified"] is False

    report = result.report_path.read_text(encoding="utf-8")
    assert "Approved: `true`" in report
    assert "Readiness score: `1.0`" in report
    assert "Network used: `false`" in report
    assert "Provider keys used: `false`" in report
    assert "Production modified: `false`" in report


def test_execution_is_deterministic_for_equivalent_inputs(tmp_path):
    executor = OfflineMockExecutor()
    first = executor.execute(
        execution_id="first",
        project="p",
        objective="o",
        output_root=tmp_path / "one",
    )
    second = executor.execute(
        execution_id="first",
        project="p",
        objective="o",
        output_root=tmp_path / "two",
    )

    first_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert first_manifest == second_manifest
    assert first.report_path.read_bytes() == second.report_path.read_bytes()
    assert [path.read_bytes() for path in first.artifact_paths] == [path.read_bytes() for path in second.artifact_paths]


@pytest.mark.parametrize("execution_id", ("../escape", "nested/path", "/absolute", "..", ".", "a\\b"))
def test_path_traversal_and_unsafe_ids_are_rejected(tmp_path, execution_id):
    root = tmp_path / "output"
    with pytest.raises(ValueError):
        OfflineMockExecutor().execute(
            execution_id=execution_id,
            project="p",
            objective="o",
            output_root=root,
        )
    assert not any(root.iterdir()) if root.exists() else True


def test_output_root_must_be_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        OfflineMockExecutor().execute(
            execution_id="cycle",
            project="p",
            objective="o",
            output_root=Path("relative-output"),
        )
    assert not (tmp_path / "relative-output").exists()


def test_existing_execution_is_not_replaced(tmp_path):
    root = tmp_path / "output"
    executor = OfflineMockExecutor()
    original = executor.execute(
        execution_id="same-id",
        project="first",
        objective="first",
        output_root=root,
    )
    before = {path.relative_to(original.output_directory): path.read_bytes() for path in original.output_directory.rglob("*") if path.is_file()}

    with pytest.raises(FileExistsError):
        executor.execute(
            execution_id="same-id",
            project="second",
            objective="second",
            output_root=root,
        )

    after = {path.relative_to(original.output_directory): path.read_bytes() for path in original.output_directory.rglob("*") if path.is_file()}
    assert after == before


def test_staging_is_cleaned_when_atomic_write_fails(tmp_path, monkeypatch):
    root = tmp_path / "output"
    executor = OfflineMockExecutor()
    original_write = executor._atomic_write_text
    calls = 0

    def fail_after_first(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated write failure")
        return original_write(path, content)

    monkeypatch.setattr(executor, "_atomic_write_text", fail_after_first)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        executor.execute(
            execution_id="failed-cycle",
            project="p",
            objective="o",
            output_root=root,
        )

    assert not (root / "failed-cycle").exists()
    assert not (root / ".staging-failed-cycle").exists()
    assert list(root.iterdir()) == []


def test_no_file_outside_output_root_is_modified(tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    before = sentinel.stat().st_mtime_ns, sentinel.read_bytes()

    result = OfflineMockExecutor().execute(
        execution_id="contained",
        project="p",
        objective="o",
        output_root=tmp_path / "output",
    )

    after = sentinel.stat().st_mtime_ns, sentinel.read_bytes()
    assert after == before
    assert all(result.output_directory in path.parents for path in result.artifact_paths)
