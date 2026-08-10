"""Internal OWASP ZAP adapter for verified Security Lab targets.

The ZAP daemon is optional, network-internal, API-key protected, and never exposed on
host ports. Passive crawling is allowed only after target authorization. Active ZAP
validation is admitted only for an Owner-registered isolated security clone.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any
from urllib.parse import urlsplit

import httpx

_RISK = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "informational": "info",
    "info": "info",
}


def configured() -> bool:
    return bool(
        os.getenv("SECURITY_ZAP_URL", "").strip()
        and os.getenv("SECURITY_ZAP_API_KEY", "").strip()
    )


def _finding(alert: dict[str, Any]) -> dict[str, Any]:
    plugin = str(alert.get("pluginId") or alert.get("alertRef") or "zap")
    url = str(alert.get("url") or "")[:1000]
    param = str(alert.get("param") or "")[:300]
    title = str(alert.get("alert") or alert.get("name") or f"ZAP alert {plugin}")[:300]
    risk = _RISK.get(
        str(alert.get("risk") or alert.get("riskdesc") or "medium").split()[0].lower(),
        "medium",
    )
    cwe = str(alert.get("cweid") or "").strip()
    wasc = str(alert.get("wascid") or "").strip()
    return {
        "source": "owasp-zap",
        "category": "dast",
        "title": title,
        "severity": risk,
        "confidence": 0.82,
        "state": "observed",
        "fingerprint": hashlib.sha256(
            f"zap|{plugin}|{url}|{param}".encode()
        ).hexdigest(),
        "cwe": f"CWE-{cwe}" if cwe.isdigit() else None,
        "owasp": None,
        "location": url or None,
        "evidence": {
            "plugin_id": plugin,
            "parameter": param or None,
            "wasc_id": wasc or None,
        },
        "remediation": str(
            alert.get("solution")
            or "Confirm the alert against source/runtime evidence and apply the smallest compatible security fix."
        )[:5000],
    }


class ZapClient:
    def __init__(self) -> None:
        self.base = os.getenv("SECURITY_ZAP_URL", "").strip().rstrip("/")
        self.key = os.getenv("SECURITY_ZAP_API_KEY", "").strip()
        if not self.base or not self.key:
            raise RuntimeError("OWASP ZAP integration is not configured")

    async def _json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        query = {"apikey": self.key, **(params or {})}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(f"{self.base}{path}", params=query)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected ZAP API response")
        return payload

    async def _wait_percent(self, path: str, *, scan_id: str, timeout: int) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            payload = await self._json(path, {"scanId": scan_id})
            try:
                progress = int(payload.get("status", "0"))
            except (TypeError, ValueError):
                progress = 0
            if progress >= 100:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("ZAP scan timed out")
            await asyncio.sleep(1.0)

    async def passive(self, origin: str, *, timeout: int = 120) -> dict[str, Any]:
        await self._json(
            "/JSON/core/action/newSession/", {"name": "", "overwrite": "true"}
        )
        spider = await self._json(
            "/JSON/spider/action/scan/",
            {"url": origin, "maxChildren": "20", "subtreeOnly": "true"},
        )
        scan_id = str(spider.get("scan") or "")
        if not scan_id:
            raise RuntimeError("ZAP spider did not return a scan id")
        await self._wait_percent(
            "/JSON/spider/view/status/", scan_id=scan_id, timeout=min(timeout, 90)
        )
        deadline = asyncio.get_running_loop().time() + min(timeout, 90)
        while True:
            payload = await self._json("/JSON/pscan/view/recordsToScan/")
            try:
                remaining = int(payload.get("recordsToScan", "0"))
            except (TypeError, ValueError):
                remaining = 0
            if remaining <= 0:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("ZAP passive scanner timed out")
            await asyncio.sleep(1.0)
        return await self.alerts(origin)

    async def active_clone(self, origin: str, *, timeout: int = 300) -> dict[str, Any]:
        # Active scanning starts from a fresh isolated session, so discover the
        # target surface in that same session before launching the active engine.
        # Otherwise only the root URL may be known and parameterized routes can be
        # skipped even though the earlier passive pass crawled them.
        await self._json(
            "/JSON/core/action/newSession/", {"name": "", "overwrite": "true"}
        )
        spider = await self._json(
            "/JSON/spider/action/scan/",
            {"url": origin, "maxChildren": "100", "subtreeOnly": "true"},
        )
        spider_id = str(spider.get("scan") or "")
        if not spider_id:
            raise RuntimeError("ZAP active pre-scan spider did not return a scan id")
        await self._wait_percent(
            "/JSON/spider/view/status/",
            scan_id=spider_id,
            timeout=min(timeout, 120),
        )

        # Let passive processing settle before the active scan. This also makes
        # the discovered URL inventory stable enough to target parameterized
        # same-origin URLs explicitly after the recursive root scan.
        passive_deadline = asyncio.get_running_loop().time() + min(timeout, 90)
        while True:
            payload = await self._json("/JSON/pscan/view/recordsToScan/")
            try:
                remaining = int(payload.get("recordsToScan", "0"))
            except (TypeError, ValueError):
                remaining = 0
            if remaining <= 0:
                break
            if asyncio.get_running_loop().time() >= passive_deadline:
                raise TimeoutError("ZAP active pre-scan passive queue timed out")
            await asyncio.sleep(1.0)

        started = await self._json(
            "/JSON/ascan/action/scan/",
            {"url": origin, "recurse": "true", "inScopeOnly": "false"},
        )
        scan_id = str(started.get("scan") or "")
        if not scan_id:
            raise RuntimeError("ZAP active scanner did not return a scan id")
        await self._wait_percent(
            "/JSON/ascan/view/status/", scan_id=scan_id, timeout=timeout
        )

        # Some ZAP builds can omit query-bearing URLs from a recursive active
        # scan even though the spider discovered them. Scan a bounded set of
        # same-origin parameterized URLs explicitly. This remains clone-only,
        # uses only URLs ZAP itself discovered, and never expands to another host.
        discovered = await self._json("/JSON/core/view/urls/", {"baseurl": origin})
        raw_urls = discovered.get("urls")
        urls = raw_urls if isinstance(raw_urls, list) else []
        base = urlsplit(origin)
        parameterized: list[str] = []
        for candidate in urls:
            value = str(candidate or "")
            parsed = urlsplit(value)
            if (
                parsed.scheme == base.scheme
                and parsed.netloc == base.netloc
                and parsed.query
                and value not in parameterized
            ):
                parameterized.append(value)
            if len(parameterized) >= 20:
                break
        for url in parameterized:
            targeted = await self._json(
                "/JSON/ascan/action/scan/",
                {"url": url, "recurse": "false", "inScopeOnly": "false"},
            )
            targeted_id = str(targeted.get("scan") or "")
            if not targeted_id:
                raise RuntimeError("ZAP targeted active scan did not return a scan id")
            await self._wait_percent(
                "/JSON/ascan/view/status/",
                scan_id=targeted_id,
                timeout=min(timeout, 180),
            )
        return await self.alerts(origin)

    async def alerts(self, origin: str) -> dict[str, Any]:
        payload = await self._json(
            "/JSON/core/view/alerts/",
            {"baseurl": origin, "start": "0", "count": "1000"},
        )
        raw_alerts = payload.get("alerts")
        alerts: list[Any] = raw_alerts if isinstance(raw_alerts, list) else []
        findings = [_finding(item) for item in alerts if isinstance(item, dict)]
        return {
            "tool": "owasp-zap",
            "status": "completed",
            "finding_count": len(findings),
            "findings": findings,
        }


async def run_zap(
    origin: str, *, execution_mode: str, active: bool = False
) -> dict[str, Any]:
    if not configured():
        return {"tool": "owasp-zap", "status": "not_configured", "findings": []}
    if active and execution_mode != "intrusive_clone":
        return {"tool": "owasp-zap", "status": "blocked_requires_clone", "findings": []}
    try:
        client = ZapClient()
        return await (client.active_clone(origin) if active else client.passive(origin))
    except (httpx.HTTPError, OSError, RuntimeError, TimeoutError) as exc:
        return {
            "tool": "owasp-zap",
            "status": (
                "unavailable"
                if isinstance(exc, (httpx.HTTPError, OSError))
                else "failed"
            ),
            "error_type": type(exc).__name__,
            "findings": [],
        }
