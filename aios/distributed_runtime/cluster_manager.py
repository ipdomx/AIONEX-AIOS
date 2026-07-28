from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock


class NodeState(str, Enum):
    JOINING = "joining"
    ACTIVE = "active"
    DRAINING = "draining"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class ClusterNode:
    node_id: str
    endpoint: str
    zone: str
    capacity: int
    labels: frozenset[str] = field(default_factory=frozenset)
    state: NodeState = NodeState.JOINING
    active_tasks: int = 0
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def available_capacity(self) -> int:
        return max(0, self.capacity - self.active_tasks)


class ClusterManager:
    """Maintains distributed node membership, capacity, draining, and stale-node eviction."""

    def __init__(self, *, stale_after: timedelta = timedelta(seconds=90)) -> None:
        if stale_after.total_seconds() <= 0:
            raise ValueError("stale_after must be positive")
        self._stale_after = stale_after
        self._nodes: dict[str, ClusterNode] = {}
        self._lock = RLock()

    def join(self, node: ClusterNode) -> ClusterNode:
        if not node.node_id.strip() or not node.endpoint.strip():
            raise ValueError("node_id and endpoint are required")
        if node.capacity <= 0:
            raise ValueError("capacity must be positive")
        active = ClusterNode(
            node_id=node.node_id,
            endpoint=node.endpoint,
            zone=node.zone,
            capacity=node.capacity,
            labels=node.labels,
            state=NodeState.ACTIVE,
            active_tasks=node.active_tasks,
            joined_at=node.joined_at,
            last_seen_at=node.last_seen_at,
        )
        with self._lock:
            self._nodes[node.node_id] = active
        return active

    def heartbeat(self, node_id: str, *, active_tasks: int, now: datetime | None = None) -> ClusterNode:
        if active_tasks < 0:
            raise ValueError("active_tasks cannot be negative")
        now = now or datetime.now(timezone.utc)
        with self._lock:
            current = self._nodes.get(node_id)
            if current is None:
                raise KeyError(f"unknown node: {node_id}")
            refreshed = ClusterNode(
                node_id=current.node_id,
                endpoint=current.endpoint,
                zone=current.zone,
                capacity=current.capacity,
                labels=current.labels,
                state=current.state,
                active_tasks=active_tasks,
                joined_at=current.joined_at,
                last_seen_at=now,
            )
            self._nodes[node_id] = refreshed
            return refreshed

    def drain(self, node_id: str) -> ClusterNode:
        with self._lock:
            current = self._nodes.get(node_id)
            if current is None:
                raise KeyError(f"unknown node: {node_id}")
            draining = ClusterNode(
                node_id=current.node_id,
                endpoint=current.endpoint,
                zone=current.zone,
                capacity=current.capacity,
                labels=current.labels,
                state=NodeState.DRAINING,
                active_tasks=current.active_tasks,
                joined_at=current.joined_at,
                last_seen_at=current.last_seen_at,
            )
            self._nodes[node_id] = draining
            return draining

    def select_node(self, *, required_labels: frozenset[str] = frozenset()) -> ClusterNode | None:
        with self._lock:
            eligible = [
                node for node in self._nodes.values()
                if node.state is NodeState.ACTIVE
                and node.available_capacity > 0
                and required_labels.issubset(node.labels)
            ]
            if not eligible:
                return None
            return min(eligible, key=lambda node: (node.active_tasks / node.capacity, node.node_id))

    def evict_stale(self, *, now: datetime | None = None) -> list[ClusterNode]:
        now = now or datetime.now(timezone.utc)
        evicted: list[ClusterNode] = []
        with self._lock:
            for node_id, node in list(self._nodes.items()):
                if now - node.last_seen_at > self._stale_after:
                    offline = ClusterNode(
                        node_id=node.node_id,
                        endpoint=node.endpoint,
                        zone=node.zone,
                        capacity=node.capacity,
                        labels=node.labels,
                        state=NodeState.OFFLINE,
                        active_tasks=node.active_tasks,
                        joined_at=node.joined_at,
                        last_seen_at=node.last_seen_at,
                    )
                    self._nodes[node_id] = offline
                    evicted.append(offline)
        return evicted

    def list_nodes(self) -> list[ClusterNode]:
        with self._lock:
            return sorted(self._nodes.values(), key=lambda node: node.node_id)
