from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "monitoring" / "fr22_external_watch.py"


def _load():
    spec = importlib.util.spec_from_file_location("fr22_external_watch", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_exact_origin_requires_https_and_no_path_query_or_userinfo() -> None:
    m = _load()
    assert m.validate_exact_https_origin("https://API.VIP-E.NET/") == "https://api.vip-e.net"
    assert m.validate_exact_https_origin("https://api.vip-e.net:443") == "https://api.vip-e.net"
    with pytest.raises(ValueError):
        m.validate_exact_https_origin("http://api.vip-e.net")
    with pytest.raises(ValueError):
        m.validate_exact_https_origin("https://api.vip-e.net/health")
    with pytest.raises(ValueError):
        m.validate_exact_https_origin("https://user@api.vip-e.net")
    with pytest.raises(ValueError):
        m.validate_exact_https_origin("https://api.vip-e.net?x=1")


def test_healthy_observation_sets_last_success_without_events() -> None:
    m = _load()
    config = m.WatchConfig(origin="https://api.vip-e.net", stale_after_seconds=300)
    result = m.evaluate(
        config,
        m.WatchState(),
        m.Observation(
            observed_at=1000,
            health_status=200,
            ready_status=200,
            tls_not_after=1000 + 100 * 86400,
        ),
    )
    assert result.conditions == ()
    assert result.events == ()
    assert result.state.last_success_at == 1000


def test_unreachable_is_transition_only_and_deduplicated() -> None:
    m = _load()
    config = m.WatchConfig(origin="https://api.vip-e.net", stale_after_seconds=300)
    first = m.evaluate(
        config,
        m.WatchState(first_observed_at=900, last_success_at=900, last_observed_at=900),
        m.Observation(1000, None, None, None, "transport:TimeoutError"),
    )
    assert [event.kind for event in first.events] == ["target_unreachable"]
    second = m.evaluate(
        config,
        first.state,
        m.Observation(1100, None, None, None, "transport:TimeoutError"),
    )
    assert second.events == ()
    assert second.conditions == ("target_unreachable",)


def test_heartbeat_stale_uses_actual_timestamps_not_schedule_claims() -> None:
    m = _load()
    config = m.WatchConfig(origin="https://api.vip-e.net", stale_after_seconds=300)
    prior = m.WatchState(
        first_observed_at=1000,
        last_observed_at=1000,
        last_success_at=1000,
        outage_started_at=1050,
        active_conditions=("target_unreachable",),
    )
    before = m.evaluate(
        config,
        prior,
        m.Observation(1300, None, None, None, "transport:TimeoutError"),
    )
    assert "heartbeat_stale" not in before.conditions
    after = m.evaluate(
        config,
        before.state,
        m.Observation(1301, None, None, None, "transport:TimeoutError"),
    )
    assert "heartbeat_stale" in after.conditions
    assert [e.kind for e in after.events] == ["heartbeat_stale"]
    assert after.events[0].details["heartbeat_age_seconds"] == 301


def test_ready_failure_is_degraded_not_unreachable() -> None:
    m = _load()
    config = m.WatchConfig(origin="https://api.vip-e.net")
    result = m.evaluate(
        config,
        m.WatchState(),
        m.Observation(2000, 200, 503, 2000 + 100 * 86400, None),
    )
    assert result.conditions == ("target_degraded",)
    assert [event.kind for event in result.events] == ["target_degraded"]


def test_recovery_event_contains_measured_outage_duration() -> None:
    m = _load()
    config = m.WatchConfig(origin="https://api.vip-e.net")
    prior = m.WatchState(
        first_observed_at=1000,
        last_observed_at=1200,
        last_success_at=1000,
        outage_started_at=1100,
        active_conditions=("target_unreachable",),
    )
    result = m.evaluate(
        config,
        prior,
        m.Observation(1400, 200, 200, 1400 + 100 * 86400, None),
    )
    assert result.conditions == ()
    assert [event.kind for event in result.events] == ["target_recovered"]
    assert result.events[0].details["outage_duration_seconds"] == 300
    assert result.state.outage_started_at is None


def test_tls_warning_and_critical_are_deterministic_transitions() -> None:
    m = _load()
    config = m.WatchConfig(
        origin="https://api.vip-e.net",
        tls_warning_seconds=30 * 86400,
        tls_critical_seconds=7 * 86400,
    )
    warning = m.evaluate(
        config,
        m.WatchState(),
        m.Observation(1000, 200, 200, 1000 + 20 * 86400, None),
    )
    assert warning.conditions == ("tls_expiry_warning",)
    assert [e.kind for e in warning.events] == ["tls_expiry_warning"]

    critical = m.evaluate(
        config,
        warning.state,
        m.Observation(2000, 200, 200, 2000 + 3 * 86400, None),
    )
    assert critical.conditions == ("tls_expiry_critical",)
    assert [e.kind for e in critical.events] == ["tls_expiry_critical"]


def test_tls_renewal_emits_recovery_without_touching_outage_state() -> None:
    m = _load()
    config = m.WatchConfig(origin="https://api.vip-e.net")
    prior = m.WatchState(
        first_observed_at=100,
        last_observed_at=100,
        last_success_at=100,
        active_conditions=("tls_expiry_warning",),
    )
    result = m.evaluate(
        config,
        prior,
        m.Observation(200, 200, 200, 200 + 90 * 86400, None),
    )
    assert result.conditions == ()
    assert [e.kind for e in result.events] == ["tls_expiry_recovered"]


def test_state_round_trip_is_atomic_and_schema_checked(tmp_path: Path) -> None:
    m = _load()
    state = m.WatchState(
        first_observed_at=1,
        last_observed_at=2,
        last_success_at=1,
        outage_started_at=2,
        active_conditions=("target_degraded",),
    )
    target = tmp_path / "state.json"
    m.save_state_atomic(target, state)
    assert m.load_state(target) == state
    payload = json.loads(target.read_text())
    assert payload["schema"] == 1
    assert target.stat().st_mode & 0o777 == 0o600



def test_tls_probe_requires_tls_1_2_or_newer(monkeypatch) -> None:
    m = _load()

    class DummyContext:
        minimum_version = None

    context = DummyContext()
    monkeypatch.setattr(m.ssl, "create_default_context", lambda: context)

    def refuse_network(*args, **kwargs):
        raise OSError("network disabled in unit test")

    monkeypatch.setattr(m.socket, "create_connection", refuse_network)
    expires, error = m._tls_not_after(
        "https://api.vip-e.net", timeout_seconds=1.0
    )
    assert expires is None
    assert error == "tls:OSError"
    assert context.minimum_version == m.ssl.TLSVersion.TLSv1_2

def test_cli_fixture_mode_never_claims_scheduler_sla(tmp_path: Path, capsys) -> None:
    m = _load()
    obs = tmp_path / "observation.json"
    obs.write_text(
        json.dumps(
            {
                "observed_at": 1000,
                "health_status": 200,
                "ready_status": 200,
                "tls_not_after": 1000 + 90 * 86400,
                "transport_error": None,
            }
        )
    )
    state = tmp_path / "state.json"
    assert (
        m.main(
            [
                "--origin",
                "https://api.vip-e.net",
                "--state",
                str(state),
                "--observation-json",
                str(obs),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["scheduler_sla_claimed"] is False
    assert payload["origin"] == "https://api.vip-e.net"
