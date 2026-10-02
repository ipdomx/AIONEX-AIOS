from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fr06c5d12_maintenance_resume_operator",
    ROOT / "scripts/security/fr06c5d12_maintenance_resume_operator.py",
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

OP = "cd5a0e31-a49b-4fdf-b2a6-ac53a7831d17"
GEN = 41


def authority():
    return {
        "operation_id": OP,
        "generation": GEN,
        "status": "closed",
        "enabled": False,
        "full_host_closure": False,
    }


def stopped_rows():
    result = {}
    for index, (service, name) in enumerate(m.TARGETS):
        result[service] = {
            "Id": f"{index + 1:064x}",
            "Image": f"sha256:{index + 11:064x}",
            "RestartCount": 0,
            "Name": "/" + name,
            "HostConfig": {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "web-dashboard",
                    "com.docker.compose.service": service,
                    "com.docker.compose.oneoff": "False",
                }
            },
            "State": {
                "Running": False,
                "Status": "exited",
                "ExitCode": 0,
                "OOMKilled": False,
                "FinishedAt": "2026-10-01T05:00:00Z",
                "Health": {"Status": "healthy"},
            },
        }
    return result


def prior(rows):
    before = {"authority": authority(), "services": {}}
    after = {"authority": authority(), "services": {}}
    for service, _ in m.TARGETS:
        row = rows[service]
        before["services"][service] = {
            "container_id": row["Id"],
            "restart_count": 0,
            "running": True,
            "restart_policy": "no",
        }
        after["services"][service] = {
            "container_id": row["Id"],
            "restart_count": 0,
            "running": False,
            "restart_policy": "no",
            "exit_code": 0,
        }
    accepted = {
        "operation_id": OP,
        "generation": GEN,
        "services": tuple(service for service, _ in m.TARGETS),
        "graceful_stop_verified": True,
        "full_host_closure": False,
    }
    return before, after, accepted


def install(monkeypatch, tmp_path, rows):
    before, after, accepted = prior(rows)
    starts = []

    monkeypatch.setattr(m, "_authority", lambda op, gen: authority())
    monkeypatch.setattr(
        m,
        "_source_identity",
        lambda: {"source_commit": "a" * 40, "operator_sha256": "b" * 64},
    )
    monkeypatch.setattr(m, "_prior", lambda *_args: (before, after, accepted))
    monkeypatch.setattr(m, "_inspect", lambda service, _name: rows[service])

    def safe_root(path):
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY)

    monkeypatch.setattr(m, "_safe_root", safe_root)

    def run(args, timeout=20):
        assert args[:2] == ["docker", "start"]
        starts.append(args[2])
        for row in rows.values():
            if row["Id"] == args[2]:
                row["State"].update(Running=True, Status="running", ExitCode=0, OOMKilled=False)
                row["State"]["Health"] = {"Status": "healthy"}
                return args[2]
        raise AssertionError("unknown container")

    monkeypatch.setattr(m, "_run", run)
    return starts


def test_success_starts_each_exact_container_once_and_invalidates_old_closure(monkeypatch, tmp_path):
    rows = stopped_rows()
    starts = install(monkeypatch, tmp_path, rows)
    result = m.execute(
        operation_id=OP,
        generation=GEN,
        prior_root=tmp_path / "prior",
        journal_root=tmp_path / "journal",
    )
    assert starts == [rows[s]["Id"] for s, _ in m.TARGETS]
    assert result["resume_verified"] is True
    assert result["prior_full_host_closure_invalidated"] is True
    assert result["full_host_closure"] is False
    assert result["production_activation_authorized"] is False
    assert (tmp_path / "journal" / "maintenance-resume-accepted.json").is_file()


def test_existing_accepted_journal_never_starts_again(monkeypatch, tmp_path):
    rows = stopped_rows()
    starts = install(monkeypatch, tmp_path, rows)
    kwargs = dict(
        operation_id=OP,
        generation=GEN,
        prior_root=tmp_path / "prior",
        journal_root=tmp_path / "journal",
    )
    first = m.execute(**kwargs)
    assert first["resume_verified"] is True
    assert len(starts) == 3
    second = m.execute(**kwargs)
    assert second == first
    assert len(starts) == 3


def test_unresolved_start_intent_with_stopped_target_blocks_replay(monkeypatch, tmp_path):
    rows = stopped_rows()
    starts = install(monkeypatch, tmp_path, rows)
    first_id = rows[m.TARGETS[0][0]]["Id"]

    def ambiguous(args, timeout=20):
        assert args[:2] == ["docker", "start"]
        starts.append(args[2])
        if args[2] == first_id:
            return args[2]
        raise AssertionError("later service must not be reached")

    monkeypatch.setattr(m, "_run", ambiguous)
    kwargs = dict(
        operation_id=OP,
        generation=GEN,
        prior_root=tmp_path / "prior",
        journal_root=tmp_path / "journal",
    )
    with pytest.raises(m.MaintenanceResumeHalted):
        m.execute(**kwargs)
    assert starts == [first_id]
    assert (tmp_path / "journal" / "telegram-worker-start-intent.json").is_file()

    with pytest.raises(m.MaintenanceResumeHalted):
        m.execute(**kwargs)
    assert starts == [first_id]


@pytest.mark.parametrize("drift", ["id", "image", "restart", "exit", "oom", "policy"])
def test_stopped_epoch_drift_blocks_before_any_start(monkeypatch, tmp_path, drift):
    rows = stopped_rows()
    starts = install(monkeypatch, tmp_path, rows)
    row = rows["telegram-worker"]
    if drift == "id":
        row["Id"] = "f" * 64
    elif drift == "image":
        original = m._inspect
        # Current image is captured only at the resume boundary; a container ID
        # still pins one Docker object, so image drift is exercised after session
        # creation in a separate test below.
        row["State"]["ExitCode"] = 1
    elif drift == "restart":
        row["RestartCount"] = 1
    elif drift == "exit":
        row["State"]["ExitCode"] = 1
    elif drift == "oom":
        row["State"]["OOMKilled"] = True
    else:
        row["HostConfig"]["RestartPolicy"]["Name"] = "unless-stopped"
    with pytest.raises(m.MaintenanceResumeHalted):
        m.execute(
            operation_id=OP,
            generation=GEN,
            prior_root=tmp_path / "prior",
            journal_root=tmp_path / "journal",
        )
    assert starts == []


def test_image_drift_after_session_intent_blocks_start(monkeypatch, tmp_path):
    rows = stopped_rows()
    starts = install(monkeypatch, tmp_path, rows)
    original_write = m._write_new

    def write_and_drift(fd, name, value):
        original_write(fd, name, value)
        if name == "telegram-worker-start-intent.json":
            rows["telegram-worker"]["Image"] = "sha256:" + "f" * 64

    monkeypatch.setattr(m, "_write_new", write_and_drift)
    with pytest.raises(m.MaintenanceResumeHalted):
        m.execute(
            operation_id=OP,
            generation=GEN,
            prior_root=tmp_path / "prior",
            journal_root=tmp_path / "journal",
        )
    assert starts == []


def test_source_contract_has_no_recreate_restart_kill_or_policy_update():
    source = (ROOT / "scripts/security/fr06c5d12_maintenance_resume_operator.py").read_text()
    assert '["docker", "start"' in source
    for forbidden in (
        '["docker", "restart"',
        '["docker", "kill"',
        '["docker", "rm"',
        '["docker", "update"',
        '"compose", "up"',
    ):
        assert forbidden not in source
