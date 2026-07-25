from __future__ import annotations

import time
from dataclasses import dataclass

from ..models import ProviderState


@dataclass(slots=True)
class HealthRecord:
    state: ProviderState = ProviderState.UNKNOWN
    latency_ms: float = 0.0
    failures: int = 0
    successes: int = 0
    last_heartbeat: float = 0.0
    last_error: str | None = None

    @property
    def available(self) -> bool:
        return self.state in {ProviderState.HEALTHY, ProviderState.DEGRADED, ProviderState.UNKNOWN}


class ProviderHealthSystem:
    def __init__(self) -> None:
        self._records: dict[str, HealthRecord] = {}

    def heartbeat(self, provider: str, state: ProviderState, latency_ms: float = 0.0,
                  error: str | None = None) -> HealthRecord:
        record = self._records.setdefault(provider, HealthRecord())
        record.state = state
        record.latency_ms = max(0.0, latency_ms)
        record.last_heartbeat = time.time()
        record.last_error = error
        if state == ProviderState.UNAVAILABLE:
            record.failures += 1
        elif state == ProviderState.HEALTHY:
            record.successes += 1
        return record

    def record_success(self, provider: str, latency_ms: float) -> None:
        self.heartbeat(provider, ProviderState.HEALTHY, latency_ms)

    def record_failure(self, provider: str, error: BaseException | str) -> None:
        self.heartbeat(provider, ProviderState.UNAVAILABLE, error=str(error))

    def available(self, provider: str) -> bool:
        return self._records.get(provider, HealthRecord()).available

    def snapshot(self) -> dict[str, dict[str, object]]:
        return {name: {"state": item.state.value, "latency_ms": item.latency_ms,
                       "failures": item.failures, "successes": item.successes,
                       "last_heartbeat": item.last_heartbeat, "last_error": item.last_error}
                for name, item in self._records.items()}
