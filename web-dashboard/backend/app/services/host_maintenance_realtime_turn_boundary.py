"""Explicit TURN/Coturn drain boundary for Realtime host-maintenance rollout.

D9B3D consumes the D9B3C provider inventory result and records the remaining
truth boundary: LiveKit room/participant inventory can bound SFU presence, but
Coturn allocation drain is not directly observable in the current deployment
contract. This module performs no cleanup, no settlement, no admission changes,
and no rollout.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.host_maintenance_admission import SessionFactory
from app.services.host_maintenance_realtime_provider_inventory import (
    RealtimeProviderInventorySnapshot,
    collect_livekit_provider_inventory,
)

_TURN_BLOCKER_REASON = "coturn_allocation_inventory_unavailable"


class RealtimeTurnBoundaryUnavailable(RuntimeError):
    """Realtime TURN boundary cannot be evaluated without the prior inventory gate."""


@dataclass(frozen=True, slots=True)
class RealtimeTurnDrainBoundary:
    """Final source-only drain boundary before any independent 0064 rollout."""

    provider_inventory: RealtimeProviderInventorySnapshot
    live_provider_inventory_verified: bool
    livekit_room_drain_verified: bool
    connected_presence_provider_drain_verified: bool
    turn_allocation_inventory_available: bool = False
    turn_allocation_drain_verified: bool = False
    turn_allocation_blocker_reason: str = _TURN_BLOCKER_REASON
    provider_drain_verified: bool = False
    full_host_closure: bool = False
    migration_0064_rollout_allowed: bool = False
    requires_independent_rollout_window: bool = True

    @property
    def rollout_blocker_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.live_provider_inventory_verified:
            reasons.append("livekit_provider_inventory_unverified")
        if not self.livekit_room_drain_verified:
            reasons.append("livekit_aios_rooms_still_present")
        if not self.connected_presence_provider_drain_verified:
            reasons.append("livekit_participants_still_present")
        if not self.turn_allocation_drain_verified:
            reasons.append(self.turn_allocation_blocker_reason)
        return tuple(reasons)


async def evaluate_realtime_turn_boundary(
    *, session_factory: SessionFactory
) -> RealtimeTurnDrainBoundary:
    """Evaluate source truth without authorizing Production rollout or drain closure."""
    inventory = await collect_livekit_provider_inventory(session_factory=session_factory)
    if not inventory.live_provider_inventory_verified:
        raise RealtimeTurnBoundaryUnavailable("LiveKit inventory gate did not produce evidence")
    return RealtimeTurnDrainBoundary(
        provider_inventory=inventory,
        live_provider_inventory_verified=inventory.live_provider_inventory_verified,
        livekit_room_drain_verified=inventory.livekit_room_drain_verified,
        connected_presence_provider_drain_verified=(
            inventory.connected_presence_provider_drain_verified
        ),
        turn_allocation_inventory_available=False,
        turn_allocation_drain_verified=False,
        turn_allocation_blocker_reason=_TURN_BLOCKER_REASON,
        provider_drain_verified=False,
        full_host_closure=False,
        migration_0064_rollout_allowed=False,
        requires_independent_rollout_window=True,
    )
