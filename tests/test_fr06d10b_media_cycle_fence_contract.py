"""Static inventory of the supplemental cycle fence, not runtime acceptance."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "web-dashboard/backend/app/services"
BOUNDARIES = {
    "audio_song_worker": ("_arm_one_user_approved", "audio_song", 2),
    "audio_dubbing_worker": ("_advance_one", "audio_dubbing", 5),
    "three_d_worker": ("_cleanup_if_due", "three_d", 1),
}


def test_every_cycle_transaction_checks_authority_before_work():
    for module, (method, consumer, count) in BOUNDARIES.items():
        tree = ast.parse((SERVICES / (module + ".py")).read_text())
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == method)
        transactions = [node for node in ast.walk(function) if isinstance(node, ast.AsyncWith)
                        and any(isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == "session"
                                for item in node.items)]
        assert len(transactions) == count
        for transaction in transactions:
            check = transaction.body[0]
            assert isinstance(check, ast.If)
            assert ast.unparse(check.test) == "not await media_cycle_admission_open(session, consumer=" + repr(consumer) + ")"
            assert isinstance(check.body[0], ast.Return)


def test_song_balance_is_bounded_inside_the_same_guarded_work_transaction():
    source = (SERVICES / "audio_song_worker.py").read_text()
    tree = ast.parse(source)
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "_arm_one_user_approved")
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
             and ast.unparse(node.func) == "self._provider_balance_usd"]
    assert len(calls) == 1
    transactions = [node for node in ast.walk(function) if isinstance(node, ast.AsyncWith)
                    and any(isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == "session"
                            for item in node.items)]
    assert calls[0] in list(ast.walk(transactions[1]))
    assert "async with asyncio.timeout(SONG_BALANCE_TIMEOUT_SECONDS)" in ast.get_source_segment(source, transactions[1])
    cleanup = (SERVICES / "three_d_worker.py").read_text()
    assert "await finish_started_cleanup(" in cleanup
    helper = (SERVICES / "host_maintenance_media_cycles.py").read_text()
    assert "asyncio.shield(task)" in helper and "raise asyncio.CancelledError" in helper
    assert "task.cancel()" not in helper


def test_cycle_scope_does_not_claim_full_host_or_provider_drain():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    batch = next(row for row in plan["batches"] if row["id"] == "FR-06")
    item = batch["downstream_media_cycle_admission_source"]
    assert item["worker_cycle_paths"] == 3 and item["transaction_boundaries"] == 8
    for key in ["production_deployed", "all_producers_guarded", "hard_crash_cleanup_drain_verified",
                "provider_inventory_verified", "full_host_closure", "parent_batch_complete"]:
        assert item[key] is False
    assert (ROOT / "docs/project/receipts/FR-06C5D10B-downstream-media-cycle-fence.md").is_file()
