from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.security import fr06c5d11_graceful_stop_operator as ops

OP = "11111111-1111-4111-8111-111111111111"
GEN = 41


def authority():
    return {
        "operation_id": OP,
        "generation": GEN,
        "status": "closed",
        "enabled": False,
        "full_host_closure": False,
    }


def row(service: str, running: bool = True, *, exit_code: int = 0, restart: str = "no"):
    suffix = {
        "telegram-worker": "a",
        "user-telegram-worker": "b",
        "operations-observer": "c",
    }[service]
    name = dict(ops.TARGETS)[service]
    return {
        "Name": "/" + name,
        "Id": suffix * 64,
        "Image": "sha256:" + suffix * 64,
        "RestartCount": 0,
        "State": {
            "Running": running,
            "ExitCode": exit_code,
            "OOMKilled": False,
            "Health": {"Status": "healthy"} if running else None,
        },
        "HostConfig": {"RestartPolicy": {"Name": restart, "MaximumRetryCount": 0}},
        "Config": {
            "Labels": {
                "com.docker.compose.project": "web-dashboard",
                "com.docker.compose.service": service,
                "com.docker.compose.oneoff": "False",
            }
        },
    }


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    base = tmp_path / "base"
    root = base / "operation"
    monkeypatch.setattr(ops, "JOURNAL_BASE", base)
    monkeypatch.setattr(ops, "_authority", lambda operation_id, generation: authority())
    monkeypatch.setattr(
        ops,
        "_source_identity",
        lambda: {"source_commit": "d" * 40, "operator_sha256": "e" * 64},
    )
    state = {service: row(service) for service, _ in ops.TARGETS}
    monkeypatch.setattr(ops, "_inspect", lambda service, name: state[service])
    return root, state


def test_happy_path_sends_one_term_per_service_and_accepts(fake_env, monkeypatch):
    root, state = fake_env
    signals = []

    def run(args, timeout=20):
        assert args[:3] == ["docker", "kill", "--signal=SIGTERM"]
        cid = args[3]
        service = next(s for s, value in state.items() if value["Id"] == cid)
        signals.append(service)
        state[service] = row(service, running=False, exit_code=0)
        return cid

    monkeypatch.setattr(ops, "_run", run)
    result = ops.execute(operation_id=OP, generation=GEN, journal_root=root)

    assert signals == [service for service, _ in ops.TARGETS]
    assert result["graceful_stop_verified"] is True
    assert result["full_host_closure"] is False
    assert result["operation_id"] == OP and result["generation"] == GEN
    for service, _ in ops.TARGETS:
        assert (root / f"{service}-signal-intent.json").is_file()
        assert (root / f"{service}-stop-accepted.json").is_file()
    assert json.loads((root / "graceful-stop-accepted.json").read_text())[
        "graceful_stop_verified"
    ] is True


def test_running_unresolved_intent_refuses_replay(fake_env, monkeypatch):
    root, state = fake_env
    calls = []

    def first_run(args, timeout=20):
        calls.append(tuple(args))
        raise ops.GracefulStopHalted("simulated uncertain command outcome")

    monkeypatch.setattr(ops, "_run", first_run)
    with pytest.raises(ops.GracefulStopHalted):
        ops.execute(operation_id=OP, generation=GEN, journal_root=root)

    assert (root / "telegram-worker-signal-intent.json").is_file()
    assert state["telegram-worker"]["State"]["Running"] is True

    def must_not_run(args, timeout=20):
        raise AssertionError("a second signal must never be sent")

    monkeypatch.setattr(ops, "_run", must_not_run)
    with pytest.raises(ops.GracefulStopHalted, match="refusing replay"):
        ops.execute(operation_id=OP, generation=GEN, journal_root=root)


def test_stopped_exact_epoch_reconciles_without_replaying_signal(fake_env, monkeypatch):
    root, state = fake_env
    signal_count = 0

    def uncertain_after_effect(args, timeout=20):
        nonlocal signal_count
        signal_count += 1
        state["telegram-worker"] = row("telegram-worker", running=False, exit_code=0)
        raise ops.GracefulStopHalted("transport lost after effect")

    monkeypatch.setattr(ops, "_run", uncertain_after_effect)
    with pytest.raises(ops.GracefulStopHalted):
        ops.execute(operation_id=OP, generation=GEN, journal_root=root)
    assert signal_count == 1

    sent = []

    def resume(args, timeout=20):
        cid = args[3]
        service = next(s for s, value in state.items() if value["Id"] == cid)
        sent.append(service)
        state[service] = row(service, running=False, exit_code=0)
        return cid

    monkeypatch.setattr(ops, "_run", resume)
    result = ops.execute(operation_id=OP, generation=GEN, journal_root=root)
    assert "telegram-worker" not in sent
    assert sent == ["user-telegram-worker", "operations-observer"]
    assert result["graceful_stop_verified"] is True
    receipt = json.loads((root / "telegram-worker-stop-accepted.json").read_text())
    assert receipt["reconciled_after_intent"] is True
    assert receipt["replayed_signal"] is False


def test_authority_drift_before_first_signal_stops_without_effect(fake_env, monkeypatch):
    root, _ = fake_env
    count = 0

    def drift(operation_id, generation):
        nonlocal count
        count += 1
        if count >= 2:
            raise ops.GracefulStopHalted("closed maintenance authority changed")
        return authority()

    monkeypatch.setattr(ops, "_authority", drift)
    monkeypatch.setattr(
        ops,
        "_run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no signal expected")),
    )
    with pytest.raises(ops.GracefulStopHalted, match="authority changed"):
        ops.execute(operation_id=OP, generation=GEN, journal_root=root)
    assert not (root / "telegram-worker-signal-intent.json").exists()


def test_prior_block_receipt_must_prove_no_effect(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            {
                "schema": ops.BLOCK_SCHEMA,
                "operation_id": OP,
                "generation": GEN,
                "attempted_target": "telegram-worker",
                "intended_signal": "SIGTERM",
                "effect_executed": False,
                "automatic_retry": False,
                "graceful_stop_verified": False,
                "full_host_closure": False,
                "production_activation_authorized": False,
            }
        )
    )
    accepted = ops._blocked_receipt(good, OP, GEN)
    assert accepted["effect_executed"] is False
    assert len(accepted["sha256"]) == 64

    bad = tmp_path / "bad.json"
    body = json.loads(good.read_text())
    body["effect_executed"] = True
    bad.write_text(json.dumps(body))
    with pytest.raises(ops.GracefulStopHalted):
        ops._blocked_receipt(bad, OP, GEN)


def test_restart_policy_must_already_be_no(monkeypatch):
    bad = row("telegram-worker", restart="unless-stopped")
    monkeypatch.setattr(ops, "_run", lambda *a, **k: json.dumps([bad]))
    with pytest.raises(ops.GracefulStopHalted):
        ops._inspect("telegram-worker", "web-dashboard-telegram-worker-1")
