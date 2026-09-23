"""Provider-side LiveKit inventory gate for Realtime drain.

D9B3B adds a read-only LiveKit inventory check after the durable D9B3A snapshot
reports no local/ledger blockers. It never mutates provider or database state and
it deliberately keeps TURN allocation drain unverified because Coturn has no
safe allocation inventory API in the current deployment contract.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.realtime.livekit_runtime import (
    LiveKitRuntime,
    ProviderRoomInventory,
    livekit_runtime,
)
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
    provider_room_inventories: tuple[ProviderRoomInventory, ...]
    provider_participant_count: int
    live_provider_inventory_verified: bool
    livekit_room_drain_verified: bool
    connected_presence_provider_drain_verified: bool
    turn_allocation_drain_verified: bool = False
    turn_allocation_drain_blocker_reason: str = "coturn_allocation_inventory_unavailable"
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
    inventories = await runtime.list_aios_room_inventory()
    room_hashes = tuple(item.provider_room_name_sha256 for item in inventories)
    participant_count = sum(item.participant_count for item in inventories)
    return RealtimeProviderInventorySnapshot(
        drain=drain,
        provider_aios_room_hashes=room_hashes,
        provider_room_inventories=inventories,
        provider_participant_count=participant_count,
        live_provider_inventory_verified=True,
        livekit_room_drain_verified=not room_hashes,
        connected_presence_provider_drain_verified=participant_count == 0,
        turn_allocation_drain_verified=False,
        provider_drain_verified=False,
        full_host_closure=False,
    )
