from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.security import fr06c5e_runtime_authority as m


def canon(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def closure(op, gen):
    body = {
        "schema": "aionex.fr06-full-host-closure.v1",
        "operation_id": op,
        "generation": gen,
        "studio_process_drain_verified": True,
        "turn_allocation_drain_verified": True,
        "turn_credential_expiry_verified": True,
        "telegram_observer_graceful_stop_verified": True,
        "component_full_host_flags_remain_false": True,
        "full_host_closure": True,
        "production_activation_authorized": False,
    }
    body["receipt_sha256"] = hashlib.sha256(canon(body)).hexdigest()
    return body


def activation(op, gen, closed, *, issued=100):
    body = {
        "schema": "aionex.fr06c5e-activation-authority.v1",
        "source_commit": "a" * 40,
        "boot_id": str(uuid4()),
        "operation_id": op,
        "generation": gen,
        "full_host_closure_receipt_sha256": closed["receipt_sha256"],
        "host_state_receipt_sha256": hashlib.sha256(b"host").hexdigest(),
        "preflight_sha256": hashlib.sha256(b"preflight").hexdigest(),
        "boot_graph_sha256": hashlib.sha256(b"graph").hexdigest(),
        "issued_at_epoch": issued,
        "expires_at_epoch": issued + 600,
        "maintenance_closed": True,
        "full_host_closure": True,
        "production_activation_authorized": True,
    }
    body["receipt_sha256"] = hashlib.sha256(canon(body)).hexdigest()
    return body


def maintenance(op, gen):
    return {
        "operation_id": op,
        "generation": gen,
        "status": "closed",
        "enabled": False,
        "full_host_closure": False,
    }


def case():
    op, gen = str(uuid4()), 41
    closed = closure(op, gen)
    act = activation(op, gen, closed)
    return op, gen, closed, act


def bind_case(op, gen, closed, act, **kw):
    args = {
        "activation": act,
        "closure": closed,
        "maintenance": maintenance(op, gen),
        "current_source_commit": act["source_commit"],
        "current_boot_id": act["boot_id"],
        "host_state_bytes": b"host",
        "preflight_bytes": b"preflight",
        "boot_graph_bytes": b"graph",
        "now": act["issued_at_epoch"] + 1,
    }
    args.update(kw)
    return m.bind(**args)


def test_binds_exact_current_runtime_to_typed_context():
    op, gen, closed, act = case()
    result = bind_case(op, gen, closed, act)
    assert asdict(result) == {
        "source_commit": act["source_commit"],
        "boot_id": act["boot_id"],
        "maintenance_operation": op,
        "maintenance_generation": gen,
        "host_state_receipt_sha256": act["host_state_receipt_sha256"],
        "preflight_sha256": act["preflight_sha256"],
        "boot_graph_sha256": act["boot_graph_sha256"],
        "maintenance_closed": True,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_commit", "b" * 40),
        ("boot_id", str(uuid4())),
        ("operation_id", str(uuid4())),
        ("generation", 42),
        ("maintenance_closed", False),
        ("full_host_closure", False),
        ("production_activation_authorized", False),
    ],
)
def test_activation_claim_drift_is_rejected(field, value):
    op, gen, closed, act = case()
    act[field] = value
    with pytest.raises(m.RuntimeAuthorityBlocked):
        bind_case(op, gen, closed, act)


@pytest.mark.parametrize("delta", [-1, 600, 900])
def test_expired_or_not_yet_valid_authority_is_rejected(delta):
    op, gen, closed, act = case()
    with pytest.raises(m.RuntimeAuthorityBlocked):
        bind_case(op, gen, closed, act, now=act["issued_at_epoch"] + delta)


@pytest.mark.parametrize(
    "change",
    [
        {"status": "open", "enabled": True},
        {"operation_id": str(uuid4())},
        {"generation": 42},
        {"full_host_closure": True},
    ],
)
def test_current_maintenance_must_remain_same_closed_authority(change):
    op, gen, closed, act = case()
    current = maintenance(op, gen)
    current.update(change)
    with pytest.raises(m.RuntimeAuthorityBlocked):
        bind_case(op, gen, closed, act, maintenance=current)


@pytest.mark.parametrize("which", ["host", "preflight", "graph"])
def test_prerequisite_bytes_are_rehashed_not_trusted_by_filename(which):
    op, gen, closed, act = case()
    values = {
        "host_state_bytes": b"host",
        "preflight_bytes": b"preflight",
        "boot_graph_bytes": b"graph",
    }
    key = {
        "host": "host_state_bytes",
        "preflight": "preflight_bytes",
        "graph": "boot_graph_bytes",
    }[which]
    values[key] += b"-changed"
    with pytest.raises(m.RuntimeAuthorityBlocked):
        bind_case(op, gen, closed, act, **values)


def test_closure_digest_and_component_flags_are_revalidated():
    op, gen, closed, act = case()
    closed["turn_credential_expiry_verified"] = False
    with pytest.raises(m.RuntimeAuthorityBlocked):
        bind_case(op, gen, closed, act)


@pytest.mark.parametrize(
    "field,value",
    [
        ("receipt_sha256", "0" * 64),
        ("expires_at_epoch", 1000),
        ("generation", True),
    ],
)
def test_activation_digest_lifetime_and_integer_shape_are_strict(field, value):
    op, gen, closed, act = case()
    act[field] = value
    with pytest.raises(m.RuntimeAuthorityBlocked):
        bind_case(op, gen, closed, act)


def test_file_loader_requires_absolute_bounded_evidence(tmp_path):
    op, gen, closed, act = case()
    paths = {}
    for name, content in {
        "activation": json.dumps(act).encode(),
        "closure": json.dumps(closed).encode(),
        "host": b"host",
        "preflight": b"preflight",
        "graph": b"graph",
    }.items():
        path = tmp_path / name
        path.write_bytes(content)
        paths[name] = path
    result = m.bind_files(
        activation_path=paths["activation"],
        closure_path=paths["closure"],
        host_state_path=paths["host"],
        preflight_path=paths["preflight"],
        boot_graph_path=paths["graph"],
        maintenance=maintenance(op, gen),
        current_source_commit=act["source_commit"],
        current_boot_id=act["boot_id"],
        now=101,
    )
    assert result.maintenance_operation == op
    with pytest.raises(m.RuntimeAuthorityBlocked):
        m.bind_files(
            activation_path=Path("relative"),
            closure_path=paths["closure"],
            host_state_path=paths["host"],
            preflight_path=paths["preflight"],
            boot_graph_path=paths["graph"],
            maintenance=maintenance(op, gen),
            current_source_commit=act["source_commit"],
            current_boot_id=act["boot_id"],
            now=101,
        )
