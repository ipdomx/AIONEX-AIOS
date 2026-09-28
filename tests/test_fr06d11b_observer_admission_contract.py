"""Source wiring complements real PostgreSQL observer acceptance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web-dashboard/backend/app/services"


def test_observer_safety_commits_before_ordinary_admission():
    source = (APP / "operations_observer.py").read_text()
    once = source[source.index("    async def run_once"):source.index("    async def run_forever")]
    safety = once.index("pilot_runtime = await reconcile_runtime_pilots(session)")
    review = once.index("live_execution_runtime = await reconcile_stale_live_executions(session)")
    commit = once.index("await session.commit()", review)
    ordinary = once.index("async def ordinary_cycle()")
    fence = once.index("await run_observer_observation(ordinary_cycle)")
    assert safety < review < commit < ordinary < fence
    assert 'pilot_runtime["auto_disarmed"]' in once[:ordinary]
    assert 'live_execution_runtime["executions_marked_manual_review"]' in once[:ordinary]
    assert "await communications.publish_many(notifications)" in once[ordinary:fence]


def test_preflight_and_observer_shutdown_use_independent_lifetime_fence():
    source = (APP / "operations_observer.py").read_text()
    helper = (APP / "host_maintenance_observer.py").read_text()
    assert "await run_observer_observation(observation_preflight)" in source
    assert "await close_observer_admission()" in source
    assert "await asyncio.shield(task)" in helper
    assert "async with SessionLocal() as session:" in helper
    assert "poolclass=NullPool" in helper and "echo=False" in helper
    assert "from app.db.base import SessionLocal" not in helper
    assert "session.commit()" not in helper
    assert "session_factory" not in helper  # No control transition is offered by this guard.


def test_observer_receipt_keeps_safety_and_full_host_limits_explicit():
    receipt = (ROOT / "docs/project/receipts/FR-06C5D11B-observer-ordinary-admission.md").read_text()
    for marker in ("independent safety", "postcommit", "auto-disarm", "not a full-host", "FR-07", "Replicate"):
        assert marker in receipt
