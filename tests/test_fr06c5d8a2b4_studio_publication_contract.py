"""Source boundaries for acknowledged Studio filesystem effects."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "web-dashboard/backend/app/services"


def test_publication_records_reservation_before_directory_mutation():
    source = (SERVICES / "studio_artifact_publication.py").read_text()
    body = source[source.index("def publish_studio_archive("):]
    assert body.index('publication_event("reserve"') < body.index("_open_directory(")
    assert body.index('publication_event("write_intent"') < body.index("_write_bytes(")
    assert body.index('publication_event("link_intent"') < body.index("os.link(")
    assert body.index('publication_event("cleanup_intent"') < body.index("_remove_staging(")
    assert body.index('publication_event("complete"') > body.index('publication_event("staging_removed"')


def test_storage_observer_is_installed_inside_owned_thread():
    source = (SERVICES / "studio_resource_registry.py").read_text()
    body = source[source.index("async def owned_studio_thread("):source.index("async def execution_snapshot(")]
    assert 'operation == "store_artifact"' in body
    assert "with publication_observer(observer):" in body
    assert body.index("make_publication_observer(session_factory, owner, resource_id)") < body.index("def call()")
    assert body.index("with publication_observer(observer):") < body.index("successful.set()")


def test_bridge_never_uses_cross_loop_session_or_a_timeout_as_acknowledgement():
    source = (SERVICES / "studio_publication_journal.py").read_text()
    assert "asyncio.run_coroutine_threadsafe(coroutine, loop)" in source
    assert "future.result()" in source
    assert "future.result(timeout" not in source
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr in {"cancel", "uncancel", "unlink", "remove", "rmtree"} for node in calls)
    assert "loop_thread" in source and "publisher_thread" in source


def test_journal_model_has_no_cascading_business_or_execution_fk():
    tree = ast.parse((ROOT / "web-dashboard/backend/app/db/models.py").read_text())
    model = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StudioPublication")
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ForeignKey" for node in ast.walk(model))
    source = ast.unparse(model)
    assert "thread_resource_id" in source and "ownership_nonce" in source
    assert "unique=True" in source


def test_journal_never_marks_execution_or_host_clean():
    source = (SERVICES / "studio_publication_journal.py").read_text()
    assert "cleanup_verified = True" not in source
    assert "full_host_closure" not in source
    assert 'row.state = "observed" if phase == "complete" else "reserved"' in source
    snapshot = (SERVICES / "studio_resource_registry.py").read_text().split("async def execution_snapshot", 1)[1]
    assert "select(StudioPublication)" in snapshot and '"orphan_publications"' in snapshot
    assert '"full_host_closure": False' in snapshot


def test_claim_and_registration_both_reject_retained_publication():
    worker = (SERVICES / "studio_worker.py").read_text()
    registry = (SERVICES / "studio_resource_registry.py").read_text()
    assert "~select(StudioPublication.id).where(StudioPublication.job_id == StudioJob.id).exists()" in worker
    assert "prior_publication is not None" in registry


def test_migration_uses_frozen_schema_and_prohibits_destructive_downgrade():
    source = (ROOT / "web-dashboard/backend/alembic/versions/20260918_0056_studio_publication_journal.py").read_text()
    assert 'down_revision = "20260918_0055"' in source
    assert "_signature(bind, name) != _signature(bind, reference.name, temporary_schema)" in source
    assert "Publication evidence cannot be discarded by downgrade" in source
    assert "app.db.models" not in source


def test_publication_record_has_reviewed_receipt():
    receipt = ROOT / "docs/project/receipts/FR-06C5D8A2B4-studio-publication-journal.md"
    assert receipt.is_file()
    text = receipt.read_text()
    assert "No production" in text and "not execution settlement" in text
