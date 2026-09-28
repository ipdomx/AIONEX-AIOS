"""Source wiring complements the real PostgreSQL/worker-loop acceptance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "web-dashboard/backend/app/services"


def test_both_telegram_loops_gate_polls_and_recheck_received_batches():
    for name in ("telegram_worker.py", "user_telegram_worker.py"):
        source = (SERVICES / name).read_text()
        run = source[source.index("    async def run(self)"):source.index("    async def ", source.index("    async def run(self)") + 20)]
        # The nested batch belongs to run; use the whole module for invocation
        # checks instead of inferring behavior from this small static contract.
        assert "offset = await self._load_offset()" in run
        assert source.index("if not await telegram_poll_admission_open") < source.index("updates = await self.api.get_updates")
        assert "run_telegram_action(lambda: consume(updates)" in source
        assert source.index("await self._store_offset(next_offset)") < source.index("offset = next_offset")
        assert "await close_telegram_admission()" in source


def test_guard_uses_separate_connection_and_retains_started_action_on_cancel():
    source = (SERVICES / "host_maintenance_telegram.py").read_text()
    assert "poolclass=NullPool" in source
    assert "await read_admission_snapshot(session)" in source
    assert "snapshot.schema_version == REALTIME_REQUEST_SCHEMA_VERSION" in source
    assert "await asyncio.shield(task)" in source
    assert "await action()" in source
    assert "session.commit" not in source
    assert "full-host coverage" in source


def test_receipt_keeps_provider_and_production_limits_explicit():
    source = (ROOT / "docs/project/receipts/FR-06C5D11A-telegram-action-admission.md").read_text()
    for text in ("FR-07", "not a full-host", "long poll", "No production", "Replicate", "exactly-once"):
        assert text in source
