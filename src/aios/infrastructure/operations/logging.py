from __future__ import annotations
import asyncio, json, logging, os, socket, time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class StructuredLogger:
    def __init__(self, service_name: str, log_directory: str = "storage/logs"):
        self.service_name = service_name
        self.hostname = socket.gethostname()
        path = Path(log_directory)
        path.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(f"aios.{service_name}")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.FileHandler(path / f"{service_name}.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)
        self.lock = asyncio.Lock()

    async def write(self, level: str, message: str, **fields: Any) -> None:
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), "service": self.service_name,
                   "hostname": self.hostname, "pid": os.getpid(), "level": level, "message": message,
                   "fields": fields}
        async with self.lock:
            self.logger.info(json.dumps(payload, ensure_ascii=False, default=str))

    async def info(self, message: str, **fields: Any) -> None:
        await self.write("INFO", message, **fields)

    async def error(self, message: str, **fields: Any) -> None:
        await self.write("ERROR", message, **fields)

    async def critical(self, message: str, **fields: Any) -> None:
        await self.write("CRITICAL", message, **fields)


class LogAggregator:
    def __init__(self, max_logs: int = 100000):
        self.logs = deque(maxlen=max_logs)
        self.by_service_index = defaultdict(lambda: deque(maxlen=5000))
        self.lock = asyncio.Lock()

    async def add_log(self, level: str, service: str, message: str, hostname: str, fields: Dict[str, Any] | None = None):
        entry = {"timestamp": time.time(), "level": level.upper(), "service": service,
                 "message": message, "hostname": hostname, "fields": fields or {}}
        async with self.lock:
            self.logs.append(entry)
            self.by_service_index[service].append(entry)

    async def recent(self, limit: int = 100) -> list[dict]:
        async with self.lock:
            return list(self.logs)[-limit:]

    async def statistics(self) -> dict:
        async with self.lock:
            return {"total_logs": len(self.logs), "services": {k: len(v) for k, v in self.by_service_index.items()}}
