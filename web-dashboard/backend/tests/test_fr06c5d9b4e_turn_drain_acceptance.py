from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.host_maintenance_realtime_turn_acceptance import (
    TurnDrainAcceptanceUnavailable,
    accept_turn_drain,
)


def obs(op, gen, closed, seen):
    return {
        "schema": "aionex.coturn-allocation-observation.v1",
        "operation_id": op,
        "generation": gen,
        "authority": {
            "operation_id": op, "generation": gen, "status": "closed",
            "enabled": False, "full_host_closure": False,
            "changed_at": closed.isoformat(),
        },
        "observed_at": seen.isoformat(),
        "samples": [{"udp_allocations": 0}, {"udp_allocations": 0}],
        "allocation_zero_observed": True,
        "credential_expiry_verified": False,
        "turn_allocation_drain_verified": False,
        "full_host_closure": False,
    }


def test_accepts_same_authority_zero_samples_after_full_credential_quiet_interval():
    op = str(uuid4())
    closed = datetime.now(timezone.utc) - timedelta(hours=2)
    first = closed + timedelta(minutes=10)
    final = first + timedelta(hours=1)
    result = accept_turn_drain(
        first=obs(op, 8, closed, first),
        final=obs(op, 8, closed, final),
        max_credential_ttl_seconds=3600,
    )
    assert result.turn_allocation_drain_verified
    assert result.credential_expiry_verified
    assert not result.full_host_closure


def test_rejects_short_interval():
    op = str(uuid4())
    closed = datetime.now(timezone.utc) - timedelta(minutes=20)
    first = closed + timedelta(minutes=1)
    final = first + timedelta(minutes=10)
    with pytest.raises(TurnDrainAcceptanceUnavailable):
        accept_turn_drain(
            first=obs(op, 8, closed, first),
            final=obs(op, 8, closed, final),
            max_credential_ttl_seconds=3600,
        )


def test_rejects_authority_change():
    op = str(uuid4())
    closed = datetime.now(timezone.utc) - timedelta(hours=3)
    first = closed + timedelta(hours=1)
    final = first + timedelta(hours=1)
    changed = obs(op, 8, closed, final)
    changed["generation"] = 9
    with pytest.raises(TurnDrainAcceptanceUnavailable):
        accept_turn_drain(
            first=obs(op, 8, closed, first), final=changed,
            max_credential_ttl_seconds=3600,
        )


def test_rejects_nonzero_or_preaccepted_observation():
    op = str(uuid4())
    closed = datetime.now(timezone.utc) - timedelta(hours=3)
    first = closed + timedelta(hours=1)
    final = first + timedelta(hours=1)
    changed = obs(op, 8, closed, final)
    changed["samples"][1]["udp_allocations"] = 1
    with pytest.raises(TurnDrainAcceptanceUnavailable):
        accept_turn_drain(
            first=obs(op, 8, closed, first), final=changed,
            max_credential_ttl_seconds=3600,
        )
