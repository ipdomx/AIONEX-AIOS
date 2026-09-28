"""Static wiring complements, but never replaces, real ASGI/PostgreSQL acceptance."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web-dashboard/backend/app"


def test_media_file_routes_are_explicit_and_all_target_handlers_exist():
    source = (APP / "services/host_maintenance_media_http.py").read_text()
    tree = ast.parse(source)
    assigned = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "FILE_ENDPOINTS" for t in n.targets))
    names = ast.literal_eval(assigned.value.args[0])
    assert len(names) == 11
    found = set()
    for file in ("audio_song_artifacts", "identity_media", "three_d_jobs"):
        text = (APP / "api/v1/endpoints" / (file + ".py")).read_text()
        assert "route_class=MediaFileRoute" in text
        functions = {n.name for n in ast.walk(ast.parse(text)) if isinstance(n, ast.AsyncFunctionDef)}
        found |= names & functions
    assert found == names


def test_fence_uses_independent_real_authority_and_complete_asgi_lifetime():
    text = (APP / "services/host_maintenance_media_http.py").read_text()
    assert "class MediaFileRoute(APIRoute)" in text
    assert "async def handle(self, scope: Scope, receive: Receive, send: Send)" in text
    assert "async with SessionLocal() as fence:" in text
    assert text.index("await require_studio_admission(fence)") < text.index("await parent(scope, receive, send)")
    assert "await asyncio.shield(task)" in text
    assert "if not admitted and not task.done() and not acquisition_cancelled:" in text
    assert "fence.commit" not in text
    assert "create_task(guarded()" in text


def test_source_receipt_preserves_partial_scope_and_prior_FR07_closure():
    text = (ROOT / "docs/project/receipts/FR-06C5D10D-media-http-lifecycle.md").read_text()
    for marker in ("before multipart", "independent", "cancel", "not a full-host", "FR-07", "Replicate"):
        assert marker in text
