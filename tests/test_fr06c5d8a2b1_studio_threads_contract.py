"""Source boundaries; actual thread/worker/DB acceptance lives in backend tests."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web-dashboard/backend/app/services"


def test_worker_joins_both_actual_build_and_storage_functions():
    source = (APP / "studio_worker.py").read_text()
    tree = ast.parse(source)
    body = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_claimed")
    calls = [node for node in ast.walk(body) if isinstance(node, ast.Call)]
    joined = [node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "owned_studio_thread"]
    assert len(joined) == 2
    assert {node.args[5].id for node in joined} == {"build_archive", "store_artifact"}
    registry = (APP / "studio_resource_registry.py").read_text()
    assert "result = await joined_studio_thread(call)" in registry
    assert registry.index("owner, resource_id = await reserve_thread(") < registry.index("result = await joined_studio_thread(call)")
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread" for node in calls)


def test_thread_helper_does_not_cancel_future_or_swallow_cancel_as_success():
    source = (APP / "studio_thread_runtime.py").read_text()
    assert "await asyncio.shield(future)" in source
    assert "while not future.done():" in source
    assert "raise cancellation from future.exception()" in source
    assert "future.cancel(" not in source and ".uncancel(" not in source
    assert "run_in_executor(" in source and "contextvars.copy_context()" in source


def test_executor_future_cancellation_is_explicitly_uncertain():
    source = (APP / "studio_thread_runtime.py").read_text()
    assert "future.cancelled()" in source
    assert 'Studio executor completion is unverified' in source
    assert "raise StudioThreadUncertain" in source


def test_join_is_not_misrepresented_as_durable_cleanup_or_drain():
    source = (APP / "studio_thread_runtime.py").read_text()
    assert "does not create durable" in source and "prove host drain" in source
    guard = (APP / "studio_execution_guard.py").read_text()
    assert 'guard["cleanup_verified"] is not False' in guard
    worker = (APP / "studio_worker.py").read_text()
    assert '"cleanup_verified": True' not in worker


def test_thread_helper_has_no_database_filesystem_or_provider_side_effects():
    tree = ast.parse((APP / "studio_thread_runtime.py").read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module)
    assert modules <= {"__future__", "asyncio", "collections.abc", "contextvars", "functools", "typing"}
