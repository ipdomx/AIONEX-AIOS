from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ServiceInstance:
    service_name: str
    instance_id: str
    endpoint: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, str] = field(default_factory=dict)
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ServiceDiscoveryRegistry:
    """Thread-safe in-memory service discovery contract for distributed runtime nodes."""

    def __init__(self, *, stale_after: timedelta = timedelta(seconds=60)) -> None:
        if stale_after.total_seconds() <= 0:
            raise ValueError("stale_after must be positive")
        self._stale_after = stale_after
        self._instances: dict[tuple[str, str], ServiceInstance] = {}
        self._lock = RLock()

    def register(self, instance: ServiceInstance) -> ServiceInstance:
        if not instance.service_name.strip():
            raise ValueError("service_name is required")
        if not instance.instance_id.strip():
            raise ValueError("instance_id is required")
        if not instance.endpoint.strip():
            raise ValueError("endpoint is required")
        with self._lock:
            self._instances[(instance.service_name, instance.instance_id)] = instance
        return instance

    def heartbeat(self, service_name: str, instance_id: str, *, now: datetime | None = None) -> ServiceInstance:
        now = now or datetime.now(timezone.utc)
        key = (service_name, instance_id)
        with self._lock:
            current = self._instances.get(key)
            if current is None:
                raise KeyError(f"unknown service instance: {service_name}/{instance_id}")
            refreshed = ServiceInstance(
                service_name=current.service_name,
                instance_id=current.instance_id,
                endpoint=current.endpoint,
                capabilities=current.capabilities,
                metadata=dict(current.metadata),
                registered_at=current.registered_at,
                last_seen_at=now,
            )
            self._instances[key] = refreshed
            return refreshed

    def deregister(self, service_name: str, instance_id: str) -> bool:
        with self._lock:
            return self._instances.pop((service_name, instance_id), None) is not None

    def discover(
        self,
        service_name: str,
        *,
        required_capabilities: Iterable[str] = (),
        now: datetime | None = None,
    ) -> list[ServiceInstance]:
        now = now or datetime.now(timezone.utc)
        required = frozenset(required_capabilities)
        with self._lock:
            return sorted(
                [
                    instance
                    for instance in self._instances.values()
                    if instance.service_name == service_name
                    and required.issubset(instance.capabilities)
                    and now - instance.last_seen_at <= self._stale_after
                ],
                key=lambda item: (item.last_seen_at, item.instance_id),
                reverse=True,
            )

    def remove_stale(self, *, now: datetime | None = None) -> list[ServiceInstance]:
        now = now or datetime.now(timezone.utc)
        removed: list[ServiceInstance] = []
        with self._lock:
            for key, instance in list(self._instances.items()):
                if now - instance.last_seen_at > self._stale_after:
                    removed.append(self._instances.pop(key))
        return removed
