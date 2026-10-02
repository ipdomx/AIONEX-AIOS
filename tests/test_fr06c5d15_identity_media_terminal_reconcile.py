from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.security import fr06c5d15_identity_media_terminal_reconcile as m


OPERATION = "cd5a0e31-a49b-4fdf-b2a6-ac53a7831d17"
GENERATION = 41
SOURCE = {"source_commit": "7" * 40}
AUTHORITY = {
    "schema_version": 8,
    "generation": GENERATION,
    "status": "closed",
    "enabled": False,
    "operation_id": OPERATION,
    "full_host_closure": False,
}


def _hash(char: str) -> str:
    return char * 64


def _row(execution_id: str, version: int, provider_state: str, job_sha256: str) -> dict[str, object]:
    return {
        "execution_id": execution_id,
        "version": version,
        "status": "failed",
        "provider_state": provider_state,
        "job_sha256": job_sha256,
        "lease_present": False,
        "secondary_job_present": False,
        "completed": True,
    }


class Case:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, count: int = 2) -> None:
        self.root = tmp_path / "base" / "journal"
        self.states: dict[str, dict[str, object]] = {}
        self.terminals: dict[str, str] = {}
        self.provider_calls: list[str] = []
        self.settle_calls: list[str] = []
        self.fail_provider_for: set[str] = set()
        self.fail_settle_for: set[str] = set()
        for index in range(count):
            execution_id = f"exec-{index}"
            self.states[execution_id] = _row(
                execution_id,
                index + 1,
                "starting" if index % 2 == 0 else "processing",
                _hash(chr(ord("a") + index)),
            )
            self.terminals[execution_id] = "failed" if index % 2 == 0 else "canceled"

        monkeypatch.setattr(m, "BASE", tmp_path / "base")
        monkeypatch.setattr(m, "_authority", lambda operation_id, generation: dict(AUTHORITY))
        monkeypatch.setattr(m, "_source", lambda: dict(SOURCE))
        monkeypatch.setattr(m, "_candidates", self.candidates)
        monkeypatch.setattr(m, "_provider_observation", self.provider)
        monkeypatch.setattr(m, "_settle", self.settle)
        monkeypatch.setattr(m, "_state", self.state)

    def candidates(self) -> list[dict[str, object]]:
        result = []
        for value in self.states.values():
            if value["status"] == "failed" and value["provider_state"] in {"starting", "processing"}:
                result.append(
                    {
                        "execution_id": value["execution_id"],
                        "version": value["version"],
                        "provider_state": value["provider_state"],
                        "job_sha256": value["job_sha256"],
                        "lease_present": value["lease_present"],
                        "secondary_job_present": value["secondary_job_present"],
                        "completed": value["completed"],
                    }
                )
        return result

    def provider(self, execution_id: str) -> dict[str, object]:
        self.provider_calls.append(execution_id)
        if execution_id in self.fail_provider_for:
            raise OSError("simulated provider observation interruption")
        value = self.states[execution_id]
        return {
            "execution_id": execution_id,
            "version": value["version"],
            "provider_state": value["provider_state"],
            "job_sha256": value["job_sha256"],
            "provider_terminal_state": self.terminals[execution_id],
        }

    def settle(self, observation: dict[str, object]) -> dict[str, object]:
        execution_id = str(observation["execution_id"])
        self.settle_calls.append(execution_id)
        if execution_id in self.fail_settle_for:
            raise OSError("simulated settlement interruption")
        value = self.states[execution_id]
        value["version"] = int(value["version"]) + 1
        value["provider_state"] = observation["provider_terminal_state"]
        return {
            "execution_id": execution_id,
            "version": value["version"],
            "status": value["status"],
            "provider_state": value["provider_state"],
            "job_sha256": value["job_sha256"],
        }

    def state(self, execution_id: str) -> dict[str, object]:
        return dict(self.states[execution_id])


def _execute(case: Case) -> dict[str, object]:
    return m.execute(
        operation_id=OPERATION,
        generation=GENERATION,
        journal_root=case.root,
    )


def test_complete_session_settles_each_frozen_candidate_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = Case(monkeypatch, tmp_path, 2)
    result = _execute(case)

    assert result["reconciled_count"] == 2
    assert result["provider_terminal_states"] == ["canceled", "failed"]
    assert result["remaining_reconcilable_count"] == 0
    assert result["provider_mutation_performed"] is False
    assert result["provider_query_only"] is True
    assert result["business_status_changed"] is False
    assert case.provider_calls == ["exec-0", "exec-1"]
    assert case.settle_calls == ["exec-0", "exec-1"]
    assert oct(os.stat(case.root / "reconcile-session-intent.json").st_mode & 0o777) == "0o600"


def test_restart_after_first_accepted_uses_original_frozen_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = Case(monkeypatch, tmp_path, 2)
    case.fail_provider_for.add("exec-1")

    with pytest.raises(OSError):
        _execute(case)

    assert case.states["exec-0"]["provider_state"] == "failed"
    assert case.states["exec-1"]["provider_state"] == "processing"
    assert (case.root / "00-settle-accepted.json").is_file()
    assert case.candidates()[0]["execution_id"] == "exec-1"

    case.fail_provider_for.clear()
    result = _execute(case)

    assert result["reconciled_count"] == 2
    assert case.settle_calls.count("exec-0") == 1
    assert case.settle_calls.count("exec-1") == 1
    assert case.provider_calls.count("exec-0") == 1
    assert case.provider_calls.count("exec-1") == 2


def test_existing_unresolved_settlement_intent_is_never_replayed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = Case(monkeypatch, tmp_path, 1)
    case.fail_settle_for.add("exec-0")

    with pytest.raises(OSError):
        _execute(case)

    assert (case.root / "00-settle-intent.json").is_file()
    assert not (case.root / "00-settle-accepted.json").exists()
    assert case.states["exec-0"]["provider_state"] == "starting"

    case.fail_settle_for.clear()
    with pytest.raises(m.IdentityTerminalReconcileHalted, match="unresolved settlement intent"):
        _execute(case)

    assert case.provider_calls == ["exec-0"]
    assert case.settle_calls == ["exec-0"]


def test_new_candidate_after_frozen_session_is_not_silently_adopted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = Case(monkeypatch, tmp_path, 1)
    original_settle = case.settle

    def settle_and_add(observation: dict[str, object]) -> dict[str, object]:
        result = original_settle(observation)
        case.states["late"] = _row("late", 9, "starting", _hash("f"))
        case.terminals["late"] = "failed"
        return result

    monkeypatch.setattr(m, "_settle", settle_and_add)

    with pytest.raises(m.IdentityTerminalReconcileHalted, match="remain after settlement"):
        _execute(case)

    session = json.loads((case.root / "reconcile-session-intent.json").read_text())
    assert [item["execution_id"] for item in session["candidates"]] == ["exec-0"]
    assert case.states["late"]["provider_state"] == "starting"

    with pytest.raises(m.IdentityTerminalReconcileHalted, match="remain after settlement"):
        _execute(case)

    assert "late" not in case.provider_calls
    assert "late" not in case.settle_calls


def test_frozen_session_rejects_source_drift_before_provider_query(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case = Case(monkeypatch, tmp_path, 1)
    case.fail_provider_for.add("exec-0")

    with pytest.raises(OSError):
        _execute(case)

    provider_call_count = len(case.provider_calls)
    monkeypatch.setattr(m, "_source", lambda: {"source_commit": "8" * 40})

    with pytest.raises(m.IdentityTerminalReconcileHalted, match="frozen reconciliation session"):
        _execute(case)

    assert len(case.provider_calls) == provider_call_count


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "candidate_count": True},
        lambda value: {**value, "automatic_retry": True},
        lambda value: {**value, "candidates": [value["candidates"][0], value["candidates"][0]], "candidate_count": 2},
    ],
)
def test_tampered_frozen_session_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation,
) -> None:
    case = Case(monkeypatch, tmp_path, 1)
    case.fail_provider_for.add("exec-0")
    with pytest.raises(OSError):
        _execute(case)

    path = case.root / "reconcile-session-intent.json"
    value = json.loads(path.read_text())
    path.write_text(json.dumps(mutation(value), sort_keys=True) + "\n")
    os.chmod(path, 0o600)

    with pytest.raises(m.IdentityTerminalReconcileHalted):
        _execute(case)


def test_provider_reader_contains_only_read_prediction_call() -> None:
    assert ".get_prediction(" in m.PROVIDER_READER
    assert ".create_prediction(" not in m.PROVIDER_READER
    assert ".cancel" not in m.PROVIDER_READER
    assert "download_output" not in m.PROVIDER_READER
