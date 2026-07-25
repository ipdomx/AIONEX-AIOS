from __future__ import annotations
import asyncio, time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Dict, Optional

try:
    import psutil
except ImportError:
    psutil = None


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass
class NodeHealth:
    node_id: str
    hostname: str
    status: str = "UNKNOWN"
    cpu: float = 0.0
    memory: float = 0.0
    disk: float = 0.0
    latency: float = 0.0
    last_seen: float = field(default_factory=time.time)
    services: Dict[str, str] = field(default_factory=dict)


@dataclass
class ServiceHealth:
    service_name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    response_time_ms: float = 0.0
    consecutive_failures: int = 0
    last_check: float = field(default_factory=time.time)
    last_error: Optional[str] = None


class ClusterHealthManager:
    def __init__(self):
        self.nodes: Dict[str, NodeHealth] = {}
        self.lock = asyncio.Lock()

    async def register_node(self, node_id: str, hostname: str) -> None:
        async with self.lock:
            self.nodes[node_id] = NodeHealth(node_id=node_id, hostname=hostname, status="ONLINE")

    async def heartbeat(self, node_id: str, cpu: float, memory: float, disk: float,
                        latency: float, services: Optional[Dict[str, str]] = None) -> None:
        async with self.lock:
            node = self.nodes.get(node_id)
            if node is None:
                node = NodeHealth(node_id=node_id, hostname=node_id)
                self.nodes[node_id] = node
            node.cpu, node.memory, node.disk, node.latency = cpu, memory, disk, latency
            node.last_seen, node.status = time.time(), "ONLINE"
            if services is not None:
                node.services = services

    async def check_expired(self, timeout: float = 60.0) -> None:
        now = time.time()
        async with self.lock:
            for node in self.nodes.values():
                if now - node.last_seen > timeout:
                    node.status = "OFFLINE"

    async def summary(self) -> dict:
        async with self.lock:
            total = len(self.nodes)
            online = sum(n.status == "ONLINE" for n in self.nodes.values())
            return {"total_nodes": total, "online_nodes": online, "offline_nodes": total - online}

    async def get_nodes(self) -> list[dict]:
        async with self.lock:
            return [vars(node).copy() for node in self.nodes.values()]


HealthCheck = Callable[[], Awaitable[bool]]


class ServiceHealthMonitor:
    def __init__(self, failure_threshold: int = 3, degraded_latency_ms: float = 1000.0):
        self.failure_threshold = failure_threshold
        self.degraded_latency_ms = degraded_latency_ms
        self.services: Dict[str, ServiceHealth] = {}
        self.checks: Dict[str, HealthCheck] = {}
        self.lock = asyncio.Lock()

    async def register_service(self, name: str, check: HealthCheck) -> None:
        async with self.lock:
            self.checks[name] = check
            self.services[name] = ServiceHealth(service_name=name)

    async def check_service(self, name: str) -> ServiceHealth:
        async with self.lock:
            check, state = self.checks.get(name), self.services.get(name)
        if check is None or state is None:
            raise KeyError(name)
        started = time.perf_counter()
        try:
            ok = await check()
            state.last_error = None
        except Exception as exc:
            ok = False
            state.last_error = str(exc)
        state.response_time_ms = (time.perf_counter() - started) * 1000
        state.last_check = time.time()
        if ok:
            state.consecutive_failures = 0
            state.status = HealthStatus.DEGRADED if state.response_time_ms >= self.degraded_latency_ms else HealthStatus.HEALTHY
        else:
            state.consecutive_failures += 1
            state.status = HealthStatus.UNHEALTHY if state.consecutive_failures >= self.failure_threshold else HealthStatus.DEGRADED
        return state

    async def check_all(self) -> dict[str, ServiceHealth]:
        names = list(self.checks)
        results = await asyncio.gather(*(self.check_service(n) for n in names), return_exceptions=True)
        return {n: r for n, r in zip(names, results) if isinstance(r, ServiceHealth)}

    async def get_status(self) -> dict:
        async with self.lock:
            return {name: {
                "service_name": item.service_name,
                "status": item.status.value,
                "response_time_ms": item.response_time_ms,
                "consecutive_failures": item.consecutive_failures,
                "last_check": item.last_check,
                "last_error": item.last_error,
            } for name, item in self.services.items()}


class SystemResourceMonitor:
    def __init__(self):
        self.snapshot = {
            "cpu_percent": 0.0, "memory_percent": 0.0, "disk_percent": 0.0,
            "swap_percent": 0.0, "load_average": None, "process_count": 0,
            "thread_count": 0, "timestamp": time.time(),
        }
        self.lock = asyncio.Lock()

    async def collect(self) -> dict:
        if psutil is None:
            return await self.get_snapshot()
        snap = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "swap_percent": psutil.swap_memory().percent,
            "load_average": getattr(psutil, "getloadavg", lambda: None)(),
            "process_count": len(psutil.pids()),
            "thread_count": sum(p.num_threads() for p in psutil.process_iter() if p.is_running()),
            "timestamp": time.time(),
        }
        async with self.lock:
            self.snapshot = snap
        return snap

    async def get_snapshot(self) -> dict:
        async with self.lock:
            return dict(self.snapshot)

    async def is_healthy(self, cpu_limit=90.0, memory_limit=90.0, disk_limit=90.0) -> bool:
        s = await self.get_snapshot()
        return s["cpu_percent"] < cpu_limit and s["memory_percent"] < memory_limit and s["disk_percent"] < disk_limit
