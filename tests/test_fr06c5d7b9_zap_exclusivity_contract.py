"""FR-06C5D7B9 Production ZAP exclusivity source/runtime contract."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZAP = ROOT / "web-dashboard/backend/app/services/security_zap.py"
OVERLAY = ROOT / "web-dashboard/docker-compose.fr06-zap-exclusivity.yml"
PLAN = ROOT / "docs/project/PLAN.json"

DENIED = (
    "academy-course-worker", "audio-dubbing-worker", "audio-music-worker",
    "audio-song-worker", "audio-song-worker-secondary", "audio-speech-worker",
    "audio-transcript-worker", "backend", "backup-worker", "communication-worker",
    "design-image-derivative-worker", "design-image-worker", "identity-media-worker",
    "media-worker", "operations-observer", "postgres", "postgres-credential-reconciler",
    "project-worker", "security-remediation-worker", "studio-worker", "telegram-worker",
    "three-d-worker", "user-telegram-worker", "video-provider-worker",
)


def _service_block(text: str, name: str) -> str:
    marker = f"  {name}:\n"
    start = text.index(marker)
    tail = text[start + len(marker):]
    match = re.search(r"\n  [A-Za-z0-9_-]+:\n", tail)
    return tail if match is None else tail[: match.start()]


def test_production_zap_fails_closed_without_owned_runtime():
    source = ZAP.read_text()
    guard = 'os.getenv("ENVIRONMENT", "").strip().lower() == "production"'
    assert guard in source
    assert "Production ZAP requires durable scan runtime ownership" in source
    assert source.index(guard) < source.index("client = ZapClient()")


def test_database_clients_do_not_inherit_zap_credentials():
    text = OVERLAY.read_text()
    for service in DENIED:
        block = _service_block(text, service)
        assert 'SECURITY_ZAP_URL: ""' in block, service
        assert 'SECURITY_ZAP_API_KEY: ""' in block, service
    assert "  security-scan-worker:\n" not in text
    assert "  security-zap:\n" not in text


def test_plan_records_live_exclusivity_closeout_without_claiming_host_drain():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    item = fr06["host_state_cutover_admission"]["security_scan_zap_exclusivity_source"]
    assert item["source_part"] == "FR-06C5D7B9"
    assert item["production_requires_owned_runtime"] is True
    assert item["non_scan_db_clients_receive_zap_credentials"] is False
    assert item["zap_host_ports_exposed"] is False
    assert item["production_zap_exclusivity_verified"] is True
    assert item["production_deployment_verified"] is True
    assert item["production_execution_performed"] is True
    assert item["real_scan_performed_by_b9"] is False
    assert item["full_host_closure"] is False
    assert any(
        path.endswith("FR-06C5D7B9-production-rollout-closeout.md")
        for path in item["evidence"]
    )
