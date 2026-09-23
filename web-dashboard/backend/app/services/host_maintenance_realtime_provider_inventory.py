"""Provider-side LiveKit inventory gate for Realtime drain.

D9B3B adds a read-only LiveKit inventory check after the durable D9B3A snapshot
reports no local/ledger blockers. It never mutates provider or database state and
it deliberately keeps TURN allocation drain unverified because Coturn has no
safe allocation inventory API in the current deployment contract.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.realtime.livekit_runtime import LiveKitRuntime, livekit_runtime
from app.services.host_maintenance_admission import SessionFactory
from app.services.host_maintenance_realtime_drain import (
    RealtimeDrainSnapshot,
    measure_realtime_drain,
)


class RealtimeProviderInventoryUnavailable(RuntimeError):
    """The provider inventory cannot be trusted as a drain proof."""


@dataclass(frozen=True, slots=True)
class RealtimeProviderInventorySnapshot:
    drain: RealtimeDrainSnapshot
    provider_aios_room_hashes: tuple[str, ...]
    live_provider_inventory_verified: bool
    connected_presence_provider_drain_verified: bool
    turn_allocation_drain_verified: bool = False
    provider_drain_verified: bool = False
    full_host_closure: bool = False


async def collect_livekit_provider_inventory(
    *,
    session_factory: SessionFactory,
    runtime: LiveKitRuntime = livekit_runtime,
) -> RealtimeProviderInventorySnapshot:
    """Read LiveKit room inventory only after durable/local blockers are clear."""
    drain = await measure_realtime_drain(session_factory=session_factory)
    if not drain.is_clear:
        raise RealtimeProviderInventoryUnavailable(
            "durable Realtime blockers must be reconciled before provider inventory"
        )
    room_hashes = await runtime.list_aios_room_name_hashes()
    return RealtimeProviderInventorySnapshot(
        drain=drain,
        provider_aios_room_hashes=room_hashes,
        live_provider_inventory_verified=True,
        connected_presence_provider_drain_verified=not room_hashes,
        turn_allocation_drain_verified=False,
        provider_drain_verified=False,
        full_host_closure=False,
    )
