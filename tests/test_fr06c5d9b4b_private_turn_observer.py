"""Executable negative/positive tests for the private TURN observation reader."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06_turn_private_observer.py"
spec = importlib.util.spec_from_file_location("fr06_turn_private_observer", SCRIPT)
assert spec and spec.loader
obs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = obs
spec.loader.exec_module(obs)

HEADER = b"# HELP turn_total_allocations Represents current allocations number\n# TYPE turn_total_allocations gauge\n"
ZERO = HEADER + b'turn_total_allocations{type="UDP"} 0\n'
ID1, ID2 = "a" * 64, "b" * 64


def epoch(cid=ID1, **changes):
    value = obs.CoturnEpoch(cid, obs.COTURN_IMAGE, 12345, 9981, "660aa1af-f5cf-4a81-b840-658111f964b5", 501, 123, 0, "2026-09-24T01:00:00Z", ("UDP",))
    return replace(value, **changes)


@pytest.mark.parametrize("value,expected", [("0", 0), ("3", 3), ("2.0", 2), ("3e+2", 300), ("0e-1", 0)])
def test_valid_gauge(value, expected):
    counts = obs.parse_allocation_counts(HEADER + f'turn_total_allocations{{type="UDP"}} {value}\n'.encode(), ("UDP",))
    assert counts.total == expected
    assert counts.values == (("UDP", expected),)


def test_complete_two_transport_gauge():
    counts = obs.parse_allocation_counts(ZERO + b'turn_total_allocations{type="TCP"} 4\n', ("UDP", "TCP"))
    assert counts.total == 4
    assert dict(counts.values) == {"UDP": 0, "TCP": 4}


@pytest.mark.parametrize("payload", [
    b"", b"# TYPE unrelated gauge\nunrelated 0\n", HEADER,
    ZERO[:-1], ZERO + b"\xff\n", ZERO + b"\x00\n", ZERO + b"\r\n",
    ZERO.replace(b"gauge", b"counter"), ZERO + HEADER,
    ZERO.replace(b'"UDP"', b'"UNKNOWN"'), ZERO.replace(b'"UDP"', b'"udp"'),
    ZERO.replace(b'{type="UDP"}', b'{type="UDP",username="do-not-return"}'),
    ZERO.replace(b'{type="UDP"}', b'{username="do-not-return"}'),
    ZERO.replace(b'{type="UDP"}', b''),
    ZERO.replace(b' 0\n', b' NaN\n'), ZERO.replace(b' 0\n', b' +Inf\n'),
    ZERO.replace(b' 0\n', b' -1\n'), ZERO.replace(b' 0\n', b' 0.1\n'),
    ZERO.replace(b' 0\n', b' 9007199254740992\n'),
    ZERO.replace(b' 0\n', b' 1e99999999\n'),
    ZERO.replace(b' 0\n', b' 0 123456789\n'),
    ZERO + b'turn_total_allocations{type="UDP"} 0\n',
    b'turn_total_allocations{type="UDP"} 0\n' + HEADER,
    ZERO + b'turn_total_allocations_extra 0\n',
    ZERO + b"x" * 17000 + b"\n", b"x" * (obs.MAX_BYTES + 1),
])
def test_malformed_missing_or_ambiguous_gauge_is_not_zero(payload):
    with pytest.raises(obs.TurnObservationUnavailable) as error:
        obs.parse_allocation_counts(payload, ("UDP",))
    assert "do-not-return" not in str(error.value)


@pytest.mark.parametrize("required", [(), ("UDP", "UDP"), ("SCTP",), ("UDP", "TCP")])
def test_missing_or_invalid_required_transport_profile(required):
    with pytest.raises(obs.TurnObservationUnavailable):
        obs.parse_allocation_counts(ZERO, required)


def test_unexpected_transport_is_configuration_drift_not_ignored():
    with pytest.raises(obs.TurnObservationUnavailable, match="profile_mismatch"):
        obs.parse_allocation_counts(ZERO + b'turn_total_allocations{type="TCP"} 0\n', ("UDP",))


def test_unrelated_sensitive_labels_are_not_exported():
    payload = ZERO + b'other_metric{username="PRIVATE",realm="SECRET"} 99\n'
    counts = obs.parse_allocation_counts(payload, ("UDP",))
    assert "PRIVATE" not in json.dumps(asdict(counts))
    assert "SECRET" not in repr(counts)


class Reader:
    def __init__(self, ids=(ID1,), values=(0, 0)):
        self.ids = ids
        self.values = iter(values)
        self.epochs = {cid: epoch(cid, network_namespace_inode=501 + i) for i, cid in enumerate(ids)}
        self.scrapes = 0
        self.fleet_reads = 0
        self.on_scrape = lambda: None

    def instances(self):
        self.fleet_reads += 1
        return self.ids

    def epoch(self, cid):
        return self.epochs[cid]

    def scrape(self, current):
        self.scrapes += 1
        self.on_scrape()
        return obs.AllocationCounts((("UDP", next(self.values)),))


def test_two_fresh_zero_samples_never_authorize_rollout_or_provider_drain():
    reader = Reader()
    result = obs.observe_private_turn(reader, (ID1,))
    assert reader.scrapes == 2 and reader.fleet_reads == 3
    assert result.all_observed_counts_zero
    assert not result.maintenance_authority_verified
    assert not result.credential_admission_closed_verified
    assert not result.turn_allocation_drain_verified
    assert not result.provider_drain_verified
    assert not result.full_host_closure
    assert not result.migration_0064_rollout_allowed


@pytest.mark.parametrize("values", [(3, 0), (0, 3), (3, 2)])
def test_any_positive_sample_prevents_zero_observation(values):
    result = obs.observe_private_turn(Reader(values=values), (ID1,))
    assert not result.all_observed_counts_zero


def test_multiple_instances_are_not_mistaken_for_one():
    reader = Reader(ids=(ID1, ID2), values=(0, 2, 0, 0))
    result = obs.observe_private_turn(reader, (ID2, ID1))
    assert reader.scrapes == 4
    assert not result.all_observed_counts_zero
    assert tuple(e.container_id for e in result.epochs) == (ID1, ID2)


@pytest.mark.parametrize("expected", [(), (ID1, ID1), ("short-id",), ("/path",), ("a" * 63,), ("A" * 64,), (ID1, ID2)])
def test_invalid_or_incomplete_fleet_rejected_before_http(expected):
    reader = Reader()
    with pytest.raises(obs.TurnObservationUnavailable):
        obs.observe_private_turn(reader, expected)
    assert reader.scrapes == 0


def test_extra_daemon_cannot_be_ignored():
    reader = Reader(ids=(ID1, ID2))
    with pytest.raises(obs.TurnObservationUnavailable, match="instance_set"):
        obs.observe_private_turn(reader, (ID1,))
    assert reader.scrapes == 0


def test_shared_namespace_rejected():
    reader = Reader(ids=(ID1, ID2))
    reader.epochs[ID2] = epoch(ID2)
    with pytest.raises(obs.TurnObservationUnavailable, match="shared_coturn"):
        obs.observe_private_turn(reader, (ID1, ID2))
    assert reader.scrapes == 0


@pytest.mark.parametrize("changes", [
    {"host_pid": 22222}, {"process_start_ticks": 9982}, {"network_namespace_inode": 777},
    {"listener_socket_inode": 124}, {"restart_count": 1}, {"started_at": "2026-09-24T02:00:00Z"},
    {"boot_id": "64dc6bdc-1c60-4a9c-9313-ad9f667c4f09"}, {"image_id": "sha256:" + "c" * 64},
])
def test_restart_reuse_rebind_or_image_change_invalidates_observation(changes):
    reader = Reader()
    reader.on_scrape = lambda: reader.epochs.update({ID1: epoch(**changes)})
    with pytest.raises(obs.TurnObservationUnavailable, match="epoch_changed"):
        obs.observe_private_turn(reader, (ID1,))
    assert reader.scrapes == 1


def test_late_fleet_addition_rejected():
    reader = Reader()
    reader.on_scrape = lambda: setattr(reader, "ids", (ID1, ID2))
    with pytest.raises(obs.TurnObservationUnavailable, match="instance_set"):
        obs.observe_private_turn(reader, (ID1,))


def test_scrape_failure_not_converted_to_zero_or_retried():
    reader = Reader()
    def failure(_epoch):
        reader.scrapes += 1
        raise obs.TurnObservationUnavailable("allocation_metric_missing")
    reader.scrape = failure
    with pytest.raises(obs.TurnObservationUnavailable, match="metric_missing"):
        obs.observe_private_turn(reader, (ID1,))
    assert reader.scrapes == 1


def test_total_observation_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(obs.time, "monotonic", lambda: now[0])
    reader = Reader()
    reader.on_scrape = lambda: now.__setitem__(0, 31.0)
    with pytest.raises(obs.TurnObservationUnavailable, match="deadline"):
        obs.observe_private_turn(reader, (ID1,))


def socket_table(address="0100007F", inode=555, port=None):
    port = obs.METRICS_PORT if port is None else port
    return f'header\n0: {address}:{port:04X} 00000000:0000 0A 0:0 00:0 0 0 0 {inode} 1\n'


def setup_proc(tmp_path, table=None, fd_inode=555):
    (tmp_path / "net").mkdir()
    (tmp_path / "fd").mkdir()
    (tmp_path / "net/tcp").write_text(table or socket_table())
    (tmp_path / "net/tcp6").write_text("header\n")
    (tmp_path / "fd/7").symlink_to(f"socket:[{fd_inode}]")
    return tmp_path


def test_loopback_listener_owned_by_daemon(tmp_path):
    assert obs._loopback_listener(setup_proc(tmp_path)) == 555


@pytest.mark.parametrize("address", ["00000000", "0200007F", "010011AC"])
def test_wildcard_or_noncanonical_address_rejected(tmp_path, address):
    with pytest.raises(obs.TurnObservationUnavailable, match="not_private"):
        obs._loopback_listener(setup_proc(tmp_path, socket_table(address)))


def test_other_process_listener_is_not_coturn_evidence(tmp_path):
    with pytest.raises(obs.TurnObservationUnavailable, match="not_owned"):
        obs._loopback_listener(setup_proc(tmp_path, fd_inode=999))


def test_ipv6_wildcard_listener_on_same_port_rejected(tmp_path):
    proc = setup_proc(tmp_path)
    (proc / "net/tcp6").write_text(socket_table("0" * 32, inode=556))
    with pytest.raises(obs.TurnObservationUnavailable, match="not_private"):
        obs._loopback_listener(proc)


def test_malformed_socket_table_rejected(tmp_path):
    with pytest.raises(obs.TurnObservationUnavailable, match="malformed"):
        obs._loopback_listener(setup_proc(tmp_path, "header\nbad\n"))


@pytest.mark.parametrize("project", ["", "trading", "aionex-vibe", "web-dashboard;id", "$(id)", "aionex-turn-observer-lab-bad"])
def test_project_isolation_allowlist(project):
    with pytest.raises(obs.TurnObservationUnavailable):
        obs.DockerCoturnReader(project)


def test_docker_inventory_is_read_only_exact_and_label_scoped(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, ID1 + "\n", "")
    monkeypatch.setattr(obs.subprocess, "run", run)
    assert obs.DockerCoturnReader().instances() == (ID1,)
    args, kwargs = calls[0]
    assert args[:3] == ["docker", "container", "ls"]
    assert "--all" in args and "--no-trunc" in args
    assert "label=com.docker.compose.project=web-dashboard" in args
    assert kwargs["timeout"] == 5
    assert "shell" not in kwargs


def test_inspection_template_omits_credentials_env_and_raw_configuration():
    assert ".Config.Env" not in obs._INSPECT
    assert "json .Args" not in obs._INSPECT
    assert "json .Config" not in obs._INSPECT.replace("json .Config.Entrypoint", "")


@pytest.mark.parametrize("exception", [subprocess.TimeoutExpired("cmd", 5), OSError("PRIVATE_FAILURE_DETAIL")])
def test_transport_exception_details_not_leaked(monkeypatch, exception):
    def fail(*args, **kwargs):
        raise exception
    monkeypatch.setattr(obs.subprocess, "run", fail)
    with pytest.raises(obs.TurnObservationUnavailable) as error:
        obs.DockerCoturnReader._run(["docker"])
    assert "PRIVATE_FAILURE_DETAIL" not in str(error.value)


def test_http_endpoint_has_no_redirect_or_proxy_behavior(monkeypatch):
    calls = []
    class Response:
        status = 200
        def getheader(self, name, default=""):
            return "text/plain; version=0.0.4" if name == "Content-Type" else default
        def read(self, maximum):
            assert maximum == obs.MAX_BYTES + 1
            return ZERO
    class Connection:
        def __init__(self, host, port, timeout):
            calls.append((host, port, timeout))
        def request(self, method, path, headers):
            assert method == "GET" and path == "/metrics"
        def getresponse(self):
            return Response()
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(obs.http.client, "HTTPConnection", Connection)
    assert obs._scrape_loopback(("UDP",)).total == 0
    assert calls == [("127.0.0.1", 9641, 3), "closed"]


@pytest.mark.parametrize("status,ctype,encoding", [(302, "text/plain", "identity"), (500, "text/plain", "identity"), (200, "text/html", "identity"), (200, "text/plain", "gzip")])
def test_nonexact_http_contract_cannot_certify_zero(monkeypatch, status, ctype, encoding):
    class Response:
        def getheader(self, name, default=""):
            return {"Content-Type": ctype, "Content-Encoding": encoding}.get(name, default)
        def read(self, maximum):
            pytest.fail("invalid HTTP response must not be parsed")
    Response.status = status
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(obs.http.client, "HTTPConnection", Connection)
    with pytest.raises(obs.TurnObservationUnavailable):
        obs._scrape_loopback(("UDP",))


@pytest.mark.parametrize("values", [(), (("UDP", True),), (("UDP", -1),), (("UDP", 0.0),), (("TCP", 0),), (("UDP", 2**53),)])
def test_bad_reader_samples_cannot_be_interpreted_as_zero(values):
    reader = Reader()
    reader.scrape = lambda current: obs.AllocationCounts(values)
    with pytest.raises(obs.TurnObservationUnavailable, match="invalid_private_allocation"):
        obs.observe_private_turn(reader, (ID1,))


def metadata(**changes):
    data = {
        "id": ID1, "image": obs.COTURN_IMAGE, "pid": 12345, "running": True,
        "paused": False, "restarting": False, "restarts": 0,
        "started_at": "2026-09-24T01:00:00Z", "project": "web-dashboard",
        "service": "realtime-turn", "network_mode": "bridge", "ports": {},
        "entrypoint": ["/usr/bin/turnserver"], "udp_only_flag": True, "tcp_only_flag": False,
    }
    data.update(changes)
    return data


@pytest.mark.parametrize("changes", [
    {"id": ID2}, {"image": "sha256:" + "c" * 64}, {"pid": 0}, {"pid": True},
    {"running": False}, {"paused": True}, {"restarting": True}, {"restarts": -1},
    {"restarts": True}, {"project": "aionex-trading"}, {"service": "unrelated"},
    {"network_mode": "host"}, {"network_mode": "container:" + ID2},
    {"network_mode": None}, {"ports": {"9641/tcp": []}}, {"ports": ["bad"]},
    {"entrypoint": ["/bin/sh"]}, {"started_at": None}, {"udp_only_flag": "false"},
])
def test_daemon_identity_policy_rejects_unsafe_or_malformed_metadata(monkeypatch, changes):
    monkeypatch.setattr(obs.os, "geteuid", lambda: 0)
    reader = obs.DockerCoturnReader()
    monkeypatch.setattr(reader, "_run", lambda args: json.dumps(metadata(**changes)))
    with pytest.raises(obs.TurnObservationUnavailable, match="binding_invalid"):
        reader.epoch(ID1)


def test_conflicting_relay_profile_flags_fail_closed(monkeypatch):
    monkeypatch.setattr(obs.os, "geteuid", lambda: 0)
    reader = obs.DockerCoturnReader()
    monkeypatch.setattr(reader, "_run", lambda args: json.dumps(metadata(tcp_only_flag=True)))
    with pytest.raises(obs.TurnObservationUnavailable, match="conflicting"):
        reader.epoch(ID1)


def test_nonroot_epoch_collection_is_rejected_without_command(monkeypatch):
    monkeypatch.setattr(obs.os, "geteuid", lambda: 1000)
    reader = obs.DockerCoturnReader()
    monkeypatch.setattr(reader, "_run", lambda args: pytest.fail("must not run Docker"))
    with pytest.raises(obs.TurnObservationUnavailable, match="root_and_exact"):
        reader.epoch(ID1)
