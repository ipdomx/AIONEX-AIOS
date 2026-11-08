"""P6 gate 6.3: the fault matrix covers every NS-14A acceptance case."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("p6_stream_fault_matrix", ROOT / "scripts/resilience/p6_stream_fault_matrix.py")
matrix = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = matrix
spec.loader.exec_module(matrix)


def test_every_plan_case_has_a_scenario():
    cases = matrix.load_cases()
    assert len(cases) >= 10
    built = matrix.build_matrix(cases)
    assert {row.case for row in built} >= set(cases)
    assert {"automated", "disruptive", "browser"} == {row.mode for row in built}


def test_unknown_case_is_never_silently_skipped():
    with pytest.raises(ValueError):
        matrix.build_matrix(["a brand new NS-14A case"])


def test_disruptive_targets_are_allow_listed():
    for row in matrix.build_matrix(matrix.load_cases()):
        if row.mode == "disruptive":
            assert row.container in matrix.DISRUPTIVE_CONTAINERS
    assert "web-dashboard-postgres-1" not in matrix.DISRUPTIVE_CONTAINERS


def test_plan_is_dry_and_targets_only_the_api(capsys):
    assert matrix.main(["plan"]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests_sent"] == 0
    assert matrix.main(["run", "--target", "https://ai.vip-e.net", "--execute"]) == 2
    capsys.readouterr()
    assert matrix.main(["run", "--execute", "--confirm-target", "api.vip-e.net",
                        "--email", "owner@example.com", "--password-file", "/dev/null"]) == 2


def test_summary_states():
    assert matrix.summarize([{"status": "PASS"}, {"status": "SHARED"}])["status"] == "PASS"
    assert matrix.summarize([{"status": "PASS"}, {"status": "MANUAL"}])["status"] == "PARTIAL_PASS_MANUAL_PENDING"
    assert matrix.summarize([{"status": "FAIL"}, {"status": "MANUAL"}])["status"] == "FAIL"


def test_turn_rows_count_as_one_reply_for_the_request():
    import asyncio
    import uuid

    conversation = str(uuid.uuid4())
    request_id = "p6-faults-x-term-1"
    turn = str(uuid.uuid5(uuid.UUID(conversation), "user-turn:" + request_id))
    rows = [
        {"id": turn, "user_message": "hi", "assistant_message": "One sentence.", "status": "completed"},
        {"id": str(uuid.uuid4()), "user_message": "other", "assistant_message": "x", "status": "completed"},
    ]

    class Response:
        status = 200

        def json(self):
            return {"messages": rows}

    class Client:
        async def get(self, path):
            return Response()

    replies, terminal = asyncio.run(matrix._replies_for(Client(), conversation, request_id))
    assert (replies, terminal) == (1, True)
    rows[0].update(assistant_message=None, status="running")
    assert asyncio.run(matrix._replies_for(Client(), conversation, request_id)) == (0, False)
