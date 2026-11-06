"""Scan summary bookkeeping: deduplicated severity counts and worker-side availability."""

from types import SimpleNamespace

import pytest

from app.services import security_tools
from app.services.security_scanning import (
    RESOLVED_AT_EXECUTION,
    build_tool_plan,
    deduplicate_findings,
    resolve_tool_availability,
    unique_severity_counts,
)


class _RecordSession:
    def __init__(self, record):
        self.record = record

    async def scalar(self, _statement):
        return self.record


def _worker_record(available_ids):
    return SimpleNamespace(
        status="active",
        payload={
            "available_ids": list(available_ids),
            "checked_at": "2026-11-06T00:00:00+00:00",
        },
    )


def test_severity_counts_cover_unique_findings_with_report_bucketing():
    findings = [
        {"fingerprint": "a", "severity": "medium"},
        {"fingerprint": "b", "severity": "MEDIUM"},
        {"fingerprint": "c", "severity": "critical"},
        {"fingerprint": "d", "severity": "unknown-scale"},
        {"fingerprint": "e"},
    ]
    assert unique_severity_counts(findings) == {
        "critical": 1,
        "high": 0,
        "medium": 2,
        "low": 0,
        "info": 2,
    }


def test_summary_counts_match_findings_table_after_dedup():
    # Same finding reported by two engines plus repeats: 4 raw medium, 2 unique.
    raw = [
        {"fingerprint": "hdr-csp", "severity": "medium", "source": "aionex-headers"},
        {"fingerprint": "hdr-csp", "severity": "medium", "source": "zap-baseline"},
        {"fingerprint": "cookie", "severity": "medium"},
        {"fingerprint": "cookie", "severity": "medium"},
        {"severity": "low", "title": "no fingerprint"},
        {"severity": "low", "title": "no fingerprint"},
    ]
    unique = deduplicate_findings(raw)
    assert list(unique)[:2] == ["hdr-csp", "cookie"]
    assert unique["hdr-csp"]["source"] == "aionex-headers"
    assert len(unique) == 3
    counts = unique_severity_counts(list(unique.values()))
    assert counts["medium"] == 2
    assert counts["low"] == 1
    assert sum(counts.values()) == len(unique)


def test_plan_without_worker_record_says_resolved_at_execution(monkeypatch):
    def api_probe(_name):
        raise AssertionError("API process must not decide optional tool availability")

    monkeypatch.setattr(security_tools.shutil, "which", api_probe)
    plan = build_tool_plan("standard", source_available=False, execution_mode="active_safe")
    optional = [item for item in plan if not item["builtin"]]
    assert optional
    assert all(item["available"] is None for item in optional)
    assert all(item["availability"] == RESOLVED_AT_EXECUTION for item in optional)
    assert all(item["available"] is True for item in plan if item["builtin"])


@pytest.mark.asyncio
async def test_plan_uses_scan_worker_runtime_record():
    catalog = await security_tools.runtime_catalog_snapshot(
        _RecordSession(_worker_record(["nuclei", "testssl"]))
    )
    plan = build_tool_plan(
        "standard",
        source_available=False,
        execution_mode="active_safe",
        runtime_catalog=catalog,
    )
    by_id = {item["id"]: item for item in plan}
    assert by_id["nuclei"]["available"] is True
    assert by_id["nuclei"]["availability"] == "available"
    assert by_id["katana"]["available"] is False
    assert by_id["katana"]["availability"] == "unavailable"
    assert by_id["nuclei"]["runtime_checked_at"] == "2026-11-06T00:00:00+00:00"


@pytest.mark.asyncio
async def test_missing_worker_record_keeps_execution_resolution():
    catalog = await security_tools.runtime_catalog_snapshot(_RecordSession(None))
    plan = [{"id": "nuclei", "builtin": False, "available": False}]
    resolved = resolve_tool_availability(plan, catalog)
    assert resolved[0]["available"] is None
    assert resolved[0]["availability"] == RESOLVED_AT_EXECUTION
    assert plan[0]["available"] is False
