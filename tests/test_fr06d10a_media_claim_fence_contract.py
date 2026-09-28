"""Source inventory for the supplemental media claim fence; runtime tests are separate."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "web-dashboard/backend/app/services"
BOUNDARIES = {
    "design_image_runtime": ("design_image", ["claim"]),
    "audio_speech_runtime": ("audio_speech", ["claim", "reap_ambiguous_submissions"]),
    "audio_transcript_runtime": ("audio_transcript", ["claim"]),
    "audio_dubbing_runtime": ("audio_dubbing", ["claim"]),
    "audio_music_runtime": ("audio_music", ["claim", "reap_ambiguous_submissions"]),
    "video_runtime": ("video", ["claim", "reap_exhausted"]),
    "audio_song_runtime": ("audio_song", ["claim_audio_song_execution", "recover_expired_audio_song_executions"]),
    "identity_media_runtime": ("identity_media", ["claim_next"]),
    "three_d_worker": ("three_d", ["claim"]),
    "media_render_worker": ("media_render", ["claim", "reap_exhausted_leases"]),
    "design_image_derivative_worker": ("design_image_derivative", ["claim", "reap_exhausted_leases"]),
}


def test_every_declared_claim_and_reaper_fences_before_its_transactional_work():
    checked = 0
    for module, (consumer, methods) in BOUNDARIES.items():
        tree = ast.parse((SERVICES / (module + ".py")).read_text())
        for method in methods:
            functions = [node for node in ast.walk(tree)
                         if isinstance(node, ast.AsyncFunctionDef) and node.name == method]
            assert len(functions) == 1
            function = functions[0]
            if any(arg.arg == "session" for arg in function.args.args):
                body = function.body
            else:
                transactions = [node for node in ast.walk(function) if isinstance(node, ast.AsyncWith)
                    and any(isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == "session"
                            for item in node.items)]
                assert len(transactions) == 1
                body = transactions[0].body
            assert isinstance(body[0], ast.If)
            assert ast.unparse(body[0].test) == (
                "not await media_claim_admission_open(session, consumer=" + repr(consumer) + ")"
            )
            assert len(body[0].body) == 1 and isinstance(body[0].body[0], ast.Return)
            checked += 1
    assert checked == 17


def test_helper_preserves_existing_lock_and_never_claims_runtime_completion():
    path = SERVICES / "host_maintenance_media_claims.py"
    text = path.read_text()
    calls = [ast.unparse(node.func) for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Call)]
    assert "require_studio_admission" in calls
    assert not any(call.endswith((".commit", ".rollback", ".add", ".flush", ".delete")) for call in calls)
    assert "HostMaintenanceClosed" in text and "HostMaintenanceUnavailable" in text
    assert "not a drain certificate" in text
    assert "provider submission/publication" in text


def test_plan_retains_remaining_producer_provider_and_deployment_requirements():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    batch = next(row for row in plan["batches"] if row["id"] == "FR-06")
    item = batch["downstream_media_claim_admission_source"]
    assert item["source_part"] == "FR-06C5D10A"
    assert item["guarded_claim_paths"] == 11 and item["guarded_reaper_paths"] == 6
    assert item["same_transaction_shared_lock"] is True
    for key in ("database_migration_required", "versioned_scope_widened", "production_deployed",
                "all_producers_guarded", "preclosure_provider_work_drained", "full_host_closure",
                "parent_batch_complete"):
        assert item[key] is False
    assert batch["host_state_cutover_admission"]["remaining_before_host_cutover_ar"]
    assert (ROOT / "docs/project/receipts/FR-06C5D10A-downstream-media-claim-fence.md").is_file()
