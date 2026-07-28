from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RuntimeNode:
    node_id: str
    capacity: int
    active_tasks: int = 0
    healthy: bool = True
    draining: bool = False

    @property
    def available_slots(self) -> int:
        return max(0, self.capacity - self.active_tasks)

    @property
    def utilization(self) -> float:
        if self.capacity <= 0:
            return 1.0
        return min(1.0, self.active_tasks / self.capacity)


class LoadBalancer:
    """Selects the healthiest least-loaded node with deterministic tie-breaking."""

    def select(self, nodes: Iterable[RuntimeNode]) -> RuntimeNode | None:
        candidates = [
            node
            for node in nodes
            if node.healthy and not node.draining and node.available_slots > 0
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda node: (
                node.utilization,
                -node.available_slots,
                node.node_id,
            ),
        )

    def rank(self, nodes: Iterable[RuntimeNode]) -> tuple[RuntimeNode, ...]:
        candidates = [
            node
            for node in nodes
            if node.healthy and not node.draining and node.available_slots > 0
        ]
        return tuple(
            sorted(
                candidates,
                key=lambda node: (
                    node.utilization,
                    -node.available_slots,
                    node.node_id,
                ),
            )
        )
