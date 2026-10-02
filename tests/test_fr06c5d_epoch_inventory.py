"""Independent synthetic tests: no Docker, database, provider or host effects.

This is NOT the previously blocked C5D suite and does not accept its patch.
The new pure verifier remains unintegrated pending protected source review.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from scripts.security import fr06c5d_epoch_inventory as m

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)  # synthetic test clock
OPERATION = "11111111-1111-4111-8111-111111111111"
BOOT = "22222222-2222-4222-8222-222222222222"


def _row(service, number=1):
    name = f"web-dashboard-{service}-{number}"
    running = service not in (*m.DRAINED, *m.ONESHOTS)
    return {
        "Id": hashlib.sha256(name.encode()).hexdigest(), "Name": "/" + name,
        "Image": "sha256:" + hashlib.sha256(service.encode()).hexdigest(), "RestartCount": 0,
        "Config": {"Labels": {"com.docker.compose.project": "web-dashboard",
                              "com.docker.compose.service": service, "com.docker.compose.oneoff": "False"},
                   "Healthcheck": {"Test": ["CMD", "synthetic-health"]} if service != "cloudflared" else {}},
        "HostConfig": {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
        "State": {"Running": running, "Status": "running" if running else "exited", "ExitCode": 0,
                  "Paused": False, "Restarting": False, "Dead": False, "OOMKilled": False,
                  "Health": {"Status": "healthy"} if running else {}},
    }


def _bind(data):
    data["binding"] = replace(data["binding"], before_sha256=m.evidence_digest(data["before"]),
                              after_sha256=m.evidence_digest(data["after"]),
                              stop_receipts_sha256=m.evidence_digest(data["stop_receipts"]))


@pytest.fixture
def evidence():
    rows = [_row(s) for s in (*m.RUNNING_SINGLETONS, *m.DRAINED, *m.ONESHOTS)]
    rows += [_row("project-worker", i) for i in range(1, 5)]
    authority = {"operation_id": OPERATION, "generation": 41, "status": "closed",
                 "enabled": False, "full_host_closure": False}
    before = {"authority": dict(authority), "services": {}}
    after = {"authority": dict(authority), "services": {}}
    receipts = {}
    for row in rows:
        service = row["Config"]["Labels"]["com.docker.compose.service"]
        if service not in m.DRAINED:
            continue
        base = {"container_id": row["Id"], "restart_count": 0, "running": True, "restart_policy": "no"}
        before["services"][service] = base
        after["services"][service] = {**base, "running": False, "exit_code": 0}
        receipts[service] = {"operation_id": OPERATION, "generation": 41, "service": service,
                             "container_id": row["Id"], "image": row["Image"], "restart_count": 0,
                             "signal": "SIGTERM", "exit_code": 0, "forced_kill": False,
                             "replayed_signal": False}
    data = {"observation": {"schema": m.SCHEMA, "source_commit": "a" * 40, "boot_id": BOOT,
                             "observed_at": NOW.isoformat(), "authority": {"schema_version": 8, **authority},
                             "all_container_ids": [r["Id"] for r in rows], "containers": rows},
            "before": before, "after": after, "stop_receipts": receipts, "now": NOW,
            "binding": m.Binding("a" * 40, BOOT, OPERATION, 41, "0" * 64, "0" * 64, "0" * 64)}
    _bind(data)
    return data


def _service(data, name):
    return next(r for r in data["observation"]["containers"]
                if r["Config"]["Labels"]["com.docker.compose.service"] == name)


def _set(obj, path, value):
    for component in path[:-1]:
        obj = obj[component]
    obj[path[-1]] = value


def test_valid_inventory_is_only_a_pure_inventory(evidence):
    result = m.verify(**evidence)
    assert len(result.containers) == 36
    assert len(result.running_ids) == 33
    assert len(result.drained_ids) == 3
    assert len(result.oneshots) == 4
    assert not set(result.running_ids) & set(result.drained_ids)
    assert result.full_host_closure is False
    assert result.production_activation_authorized is False


def test_result_is_immutable_and_not_aliased_to_mutable_evidence(evidence):
    result = m.verify(**evidence)
    before = result.containers
    evidence["observation"]["containers"][0]["Id"] = "f" * 64
    assert result.containers == before
    with pytest.raises(FrozenInstanceError):
        result.containers[0].desired_state = "running"


@pytest.mark.parametrize("path,value", [
    (("source_commit",), "b" * 40), (("boot_id",), OPERATION),
    (("authority", "generation"), 42), (("authority", "operation_id"), BOOT),
    (("authority", "status"), "open"), (("authority", "enabled"), True),
    (("authority", "enabled"), 0), (("authority", "full_host_closure"), 0),
    (("authority", "full_host_closure"), True), (("authority", "schema_version"), 9),
    (("observed_at",), (NOW - timedelta(seconds=121)).isoformat()),
    (("observed_at",), (NOW + timedelta(microseconds=1)).isoformat()),
    (("observed_at",), "2026-01-01T12:00:00"), (("observed_at",), "not-a-time"),
    (("schema",), "wrong-schema"),
])
def test_source_authority_boot_and_freshness_are_exact(evidence, path, value):
    _set(evidence["observation"], path, value)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


@pytest.mark.parametrize("path,value", [
    (("Image",), "sha256:" + "f" * 64), (("RestartCount",), 1), (("RestartCount",), False),
    (("HostConfig", "RestartPolicy", "Name"), "unless-stopped"),
    (("HostConfig", "RestartPolicy", "MaximumRetryCount"), 1),
    (("State", "ExitCode"), False), (("State", "ExitCode"), 137),
    (("State", "OOMKilled"), True), (("State", "OOMKilled"), None),
    (("State", "Dead"), True), (("State", "Paused"), True),
    (("State", "Restarting"), True), (("State", "Running"), True),
    (("State", "Running"), 0), (("State", "Status"), "created"),
    (("Config", "Labels", "com.docker.compose.oneoff"), "True"),
    (("Config", "Labels", "com.docker.compose.project"), "other-project"),
])
def test_same_name_and_clean_exit_are_not_accepted_epoch(evidence, path, value):
    _set(_service(evidence, "telegram-worker"), path, value)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


@pytest.mark.parametrize("field,value", [
    ("container_id", "f" * 64), ("image", "sha256:" + "f" * 64), ("restart_count", 1),
    ("restart_count", False), ("generation", 42), ("operation_id", BOOT),
    ("signal", "SIGKILL"), ("forced_kill", True), ("forced_kill", 0),
    ("replayed_signal", True), ("exit_code", False), ("exit_code", 137),
    ("service", "user-telegram-worker"),
])
def test_rehashing_invalid_stop_receipt_does_not_make_it_acceptable(evidence, field, value):
    evidence["stop_receipts"]["telegram-worker"][field] = value
    _bind(evidence)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


@pytest.mark.parametrize("side,field,value", [
    ("before", "running", False), ("after", "running", True),
    ("before", "restart_policy", "always"), ("after", "restart_policy", "always"),
    ("before", "container_id", "f" * 64), ("after", "container_id", "f" * 64),
    ("before", "restart_count", 1), ("after", "restart_count", 1),
    ("after", "exit_code", False), ("after", "exit_code", 137),
])
def test_raw_graceful_evidence_is_revalidated_after_digest_match(evidence, side, field, value):
    evidence[side]["services"]["telegram-worker"][field] = value
    _bind(evidence)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate_inspect", "different_inspect", "duplicate_listing"])
def test_complete_inventory_bijection(evidence, mutation):
    obs = evidence["observation"]
    if mutation == "missing":
        obs["containers"].pop()
    elif mutation == "extra":
        obs["containers"].append(_row("unknown-worker"))
        obs["all_container_ids"].append(obs["containers"][-1]["Id"])
    elif mutation == "duplicate_inspect":
        obs["containers"][-1] = copy.deepcopy(obs["containers"][0])
    elif mutation == "different_inspect":
        obs["containers"][-1]["Id"] = "f" * 64
    else:
        obs["all_container_ids"][-1] = obs["all_container_ids"][0]
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


def test_unknown_stopped_container_is_not_silently_ignored(evidence):
    row = _service(evidence, m.ONESHOTS[0])
    row["Name"] = "/web-dashboard-unknown-stopped-1"
    row["Config"]["Labels"]["com.docker.compose.service"] = "unknown-stopped"
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


@pytest.mark.parametrize("service,path,value", [
    (m.ONESHOTS[0], ("State", "ExitCode"), 1),
    (m.ONESHOTS[0], ("State", "OOMKilled"), True),
    (m.ONESHOTS[0], ("State", "Running"), True),
    ("backend", ("State", "Health", "Status"), "starting"),
    ("backend", ("Config", "Healthcheck", "Test"), ["NONE"]),
    ("backend", ("State", "Running"), False),
    ("backend", ("Config", "Labels", "com.docker.compose.service"), "other-worker"),
])
def test_oneshots_and_running_services_are_validated(evidence, service, path, value):
    _set(_service(evidence, service), path, value)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


@pytest.mark.parametrize("maximum", [0, -1, True, 301, 1.5])
def test_freshness_limit_cannot_be_disabled(evidence, maximum):
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence, max_age_seconds=maximum)


def test_forged_true_flag_is_not_a_raw_stop_receipt(evidence):
    evidence["stop_receipts"]["telegram-worker"] = {"graceful_stop_verified": True}
    _bind(evidence)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


def test_hash_change_without_commitment_update_rejected(evidence):
    evidence["stop_receipts"]["telegram-worker"]["extra"] = "not-original"
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


def test_generation_boolean_not_integer(evidence):
    evidence["binding"] = replace(evidence["binding"], generation=True)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


def test_wrong_epoch_with_same_id_in_all_raw_before_after_is_rejected_by_stop_image(evidence):
    _service(evidence, "telegram-worker")["Image"] = "sha256:" + "f" * 64
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


@pytest.mark.parametrize("service,path,value", [
    ("backend", ("HostConfig",), None),
    ("backend", ("HostConfig", "RestartPolicy"), []),
    ("backend", ("Config", "Healthcheck"), None),
    ("backend", ("State", "Health"), []),
    ("cloudflared", ("Config", "Healthcheck", "Test"), 123),
    ("cloudflared", ("Config", "Healthcheck", "Test"), [123]),
    ("cloudflared", ("Config", "Healthcheck", "Test"), ["UNSUPPORTED"]),
])
def test_malformed_nested_records_are_explicitly_rejected(evidence, service, path, value):
    _set(_service(evidence, service), path, value)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


def test_naive_clock_cannot_supply_freshness(evidence):
    evidence["now"] = NOW.replace(tzinfo=None)
    with pytest.raises(m.InventoryBlocked):
        m.verify(**evidence)


def test_no_host_io_in_independent_core():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(m.__file__).read_text())
    imports = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
    assert not imports.intersection({"subprocess", "os", "socket", "requests", "httpx", "shutil"})
    names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not names.intersection({"open", "eval", "exec", "compile", "__import__"})
