"""Exclusive, durable ownership of a worker's optional remote ZAP session.

Only naturally completed, acknowledged producers can release the engine after
fresh empty inventories and session cleanup. A stop ACK, timeout, lost response,
or unknown producer is never settlement. Such failures retain the engine fence
for operator reconciliation; this adapter never resets another owner's session.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from urllib.parse import urlsplit

from app.services import host_maintenance_scan_execution as registry
from app.services.security_scan_resources import ScanResourceRuntime, finish, join_task
from app.services.security_zap import ZapClient, ZapResponseInvalid, _integer_field, _scan_id


class OwnedZapClient(ZapClient):
    def __init__(self, runtime: ScanResourceRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self.identifier: str | None = None
        self.ids: dict[str, list[str]] = {"spider": [], "ascan": []}
        self.completed: set[tuple[str, str]] = set()
        self.pending = False
        self.uncertain_transport = False
        self.cleaning = False
        self.preflight_passed = False
        self.session_started = False
        parsed = urlsplit(self.base)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Invalid internal engine identity")
        canonical = f"{parsed.scheme}://{parsed.hostname.lower()}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}{parsed.path.rstrip('/')}"
        self.engine_key = hashlib.sha256(canonical.encode()).hexdigest()

    def identity(self) -> dict[str, Any]:
        return {"engine": self.engine_key, "spider_ids": list(self.ids["spider"]),
                "active_ids": list(self.ids["ascan"]), "submission_pending": self.pending,
                "session_started": self.session_started}

    async def save(self) -> None:
        assert self.identifier is not None
        await self.runtime.update(self.identifier, state="active", identity=self.identity())

    @staticmethod
    def action_ok(payload: dict[str, Any]) -> None:
        if payload != {"Result": "OK"}:
            raise ZapResponseInvalid("ZAP action acknowledgement is missing or invalid")

    async def _json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.cleaning:
            await self.runtime.checkpoint()
        mutation = "/action/" in path
        if mutation:
            self.pending = True
            await self.save()  # Durable intent must be acknowledged before I/O.
        task = asyncio.create_task(super()._json(path, params))
        try:
            payload, cancelled = await join_task(task)
        except BaseException:
            self.uncertain_transport = True
            raise
        if mutation:
            if path in {"/JSON/spider/action/scan/", "/JSON/ascan/action/scan/"}:
                kind = "spider" if "/spider/" in path else "ascan"
                identifier = _scan_id(payload)
                if identifier in self.ids[kind] or len(self.ids[kind]) >= 64:
                    raise ZapResponseInvalid("ZAP producer identity is duplicated or excessive")
                self.ids[kind].append(identifier)
            else:
                self.action_ok(payload)
            if path == "/JSON/core/action/newSession/":
                self.session_started = True
            self.pending = False
            # Join this proof write even if the caller was cancelled after its
            # request was dispatched. Lost acknowledgement still cannot release.
            try:
                await finish(self.save())
            except BaseException:
                self.uncertain_transport = True  # Lost proof ACK is also ambiguous.
                raise
        if cancelled:
            raise asyncio.CancelledError()
        return payload

    async def _wait_percent(self, path: str, *, scan_id: str, timeout: int) -> None:
        await super()._wait_percent(path, scan_id=scan_id, timeout=timeout)
        kind = "spider" if "/spider/" in path else "ascan"
        self.completed.add((kind, scan_id))

    async def inventory(self, kind: str) -> list[str]:
        payload = await self._json(f"/JSON/{kind}/view/scans/")
        values = payload.get("scans")
        if "code" in payload or not isinstance(values, list):
            raise ZapResponseInvalid("ZAP producer inventory is missing or invalid")
        result = []
        for value in values:
            if not isinstance(value, dict):
                raise ZapResponseInvalid("ZAP producer inventory item is invalid")
            identifier = str(_integer_field(value, "id"))
            if identifier in result:
                raise ZapResponseInvalid("ZAP producer inventory is duplicated")
            result.append(identifier)
        return result

    async def cleanup(self) -> None:
        assert self.identifier is not None
        self.cleaning = True
        try:
            expected = {(kind, identifier) for kind, ids in self.ids.items() for identifier in ids}
            if (self.pending or self.uncertain_transport or not self.preflight_passed
                    or not self.session_started or self.completed != expected):
                # Stop only acknowledged owned producers. No stopAll/reset, no
                # adoption of an unknown scan, no assumption that stop joined it.
                if self.preflight_passed and not self.pending and not self.uncertain_transport:
                    for kind, identifier in sorted(expected - self.completed):
                        await self._json(f"/JSON/{kind}/action/stop/", {"scanId": identifier})
                raise registry.ScanExecutionUncertain("Remote producers lack natural completion proof")
            for kind in self.ids:
                if set(await self.inventory(kind)) != set(self.ids[kind]):
                    raise registry.ScanExecutionUncertain("Remote producer ownership changed")
            await self._wait_passive_queue(timeout=90)
            for kind, ids in self.ids.items():
                for identifier in ids:
                    await self._json(f"/JSON/{kind}/action/removeScan/", {"scanId": identifier})
            for kind in self.ids:
                if await self.inventory(kind):
                    raise registry.ScanExecutionUncertain("Remote producer inventory is not empty")
            await self._json("/JSON/core/action/newSession/", {"name": "", "overwrite": "true"})
            for kind in self.ids:
                if await self.inventory(kind):
                    raise registry.ScanExecutionUncertain("Remote producer reappeared during cleanup")
            await self._wait_passive_queue(timeout=90)
            await self.runtime.update(self.identifier, state="settled", identity=self.identity(), evidence={
                "remote_zero": True, "cleanup_complete": True,
            })
        except BaseException as exc:
            await finish(self.runtime.uncertain(self.identifier, exc))
            raise

    async def run(self, origin: str, *, active: bool) -> dict[str, Any]:
        self.identifier = await self.runtime.reserve("zap", "owned-zap-session", exclusive_key=self.engine_key)
        try:
            await self.save()
            for kind in self.ids:
                if await self.inventory(kind):
                    raise registry.ScanExecutionUncertain("Remote engine contains unowned producers")
            payload = await self._json("/JSON/pscan/view/recordsToScan/")
            if _integer_field(payload, "recordsToScan") != 0:
                raise registry.ScanExecutionUncertain("Remote engine contains unowned passive work")
            self.preflight_passed = True
            return await (self.active_clone(origin) if active else self.passive(origin))
        finally:
            await finish(self.cleanup())
