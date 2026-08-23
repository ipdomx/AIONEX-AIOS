from __future__ import annotations

import subprocess
from pathlib import Path

from aios.phase36_program import (
    BATCHES,
    CAPABILITIES,
    MATURITY_ORDER,
    phase36_program_snapshot,
    phase36_reporting_violation,
)

ROOT = Path(__file__).resolve().parents[1]


def test_phase36_batches_are_complete_registry_and_36a_closes_first() -> None:
    assert [batch.batch_id for batch in BATCHES] == [
        f"36{letter}" for letter in "ABCDEFGHIJKLMN"
    ]
    assert [batch.sequence for batch in BATCHES] == list(range(1, 15))
    assert all(batch.status == "complete" for batch in BATCHES[:6])
    assert BATCHES[6].status == "in_progress"
    assert all(batch.status == "planned" for batch in BATCHES[7:])
    assert [batch.batch_id for batch in BATCHES if batch.status == "in_progress"] == ["36G"]


def test_every_phase36_capability_has_unique_owner_and_valid_maturity() -> None:
    ids = [item.capability_id for item in CAPABILITIES]
    assert len(ids) == len(set(ids))
    batch_ids = {batch.batch_id for batch in BATCHES}
    assert len(CAPABILITIES) >= 50
    for capability in CAPABILITIES:
        assert capability.owner_batch in batch_ids
        assert capability.maturity in MATURITY_ORDER
        assert capability.category
        assert capability.title


def test_phase36_taxonomy_covers_owner_required_product_families() -> None:
    categories = {item.category for item in CAPABILITIES}
    assert {
        "program",
        "scale",
        "ai",
        "software",
        "media",
        "design",
        "video",
        "audio",
        "realtime",
        "3d-xr",
        "education",
        "healthcare",
        "sectors",
        "product",
        "certification",
    } <= categories
    ids = {item.capability_id for item in CAPABILITIES}
    assert {
        "thousand-user-admission",
        "multi-provider-project-routing",
        "image-generation-editing",
        "text-image-logo-to-video",
        "long-form-ad-video",
        "song-production",
        "course-factory",
        "healthcare-administration",
        "government-public-service",
        "custom-domain-composer",
        "scale-chaos-dr",
    } <= ids


def test_phase36b_maturity_matches_production_activation_evidence() -> None:
    capabilities = {item.capability_id: item for item in CAPABILITIES}
    assert capabilities["distributed-project-execution"].maturity == "runtime_verified"
    assert capabilities["thousand-user-admission"].maturity == "locally_executed"
    assert capabilities["horizontal-worker-scaling"].maturity == "runtime_verified"
    assert BATCHES[1].status == "complete"
    assert BATCHES[2].status == "complete"
    assert BATCHES[3].status == "complete"
    assert BATCHES[4].status == "complete"
    assert BATCHES[5].status == "complete"
    assert BATCHES[6].status == "in_progress"


def test_phase36c_maturity_matches_live_provider_acceptance_evidence() -> None:
    capabilities = {item.capability_id: item for item in CAPABILITIES}
    routing = capabilities["multi-provider-project-routing"]
    assert routing.maturity == "runtime_verified"
    assert routing.external_gates == ("owner-provider-funded-credit-thresholds",)
    assert capabilities["tenant-agent-memory-isolation"].maturity == "runtime_verified"
    assert BATCHES[2].status == "complete"
    external = {
        item.capability_id: item.external_gates
        for item in CAPABILITIES
        if item.owner_batch == "36C" and item.external_gates
    }
    assert external == {
        "multi-provider-project-routing": ("owner-provider-funded-credit-thresholds",),
        "mobile-apps": ("store-signing-and-publication",),
        "desktop-apps": ("platform-code-signing",),
        "commerce-apps": ("live-payment-provider-credential",),
        "iot-robotics-contracts": ("physical-device-or-chain-deployment-authority",),
    }


def test_phase36e_maturity_matches_production_design_exit_evidence() -> None:
    capabilities = {item.capability_id: item for item in CAPABILITIES}
    for capability_id in (
        "prompt-factory",
        "image-generation-editing",
        "logo-branding",
        "infographic-experimental-graphics",
        "editable-design-exports",
    ):
        capability = capabilities[capability_id]
        assert capability.maturity == "runtime_verified"
        assert "docs/phase-36/receipts/36E-2026-08-18-design-image-foundation.md" in capability.evidence
    assert BATCHES[4].status == "complete"
    assert BATCHES[5].status == "complete"
    assert BATCHES[6].status == "in_progress"


def test_phase36f_maturity_matches_live_video_exit_evidence_without_overclaiming() -> None:
    capabilities = {item.capability_id: item for item in CAPABILITIES}
    receipt = "docs/phase-36/receipts/36F-2026-08-19-video-factory.md"
    for capability_id in (
        "text-image-logo-to-video",
        "long-form-ad-video",
        "video-continuity-resume",
    ):
        capability = capabilities[capability_id]
        assert capability.maturity == "runtime_verified"
        assert receipt in capability.evidence
    final_export = capabilities["video-final-export"]
    assert final_export.maturity == "source_built"
    assert receipt in final_export.evidence
    assert capabilities["cinema-motion-vfx"].maturity == "specified"
    assert BATCHES[5].status == "complete"
    assert BATCHES[6].status == "in_progress"


def test_phase36g_stage5_source_keeps_diarization_separate_without_overclaiming() -> None:
    capabilities = {item.capability_id: item for item in CAPABILITIES}
    receipt = "docs/phase-36/receipts/36G-2026-08-21-audio-foundation.md"
    expected = {
        "stock-voice-tts": "runtime_verified",
        "governed-stt-transcript": "runtime_verified",
        "multi-speaker-diarization": "runtime_verified",
        "complete-stock-voice-dubbing": "runtime_verified",
        "stt-tts-dubbing": "source_built",
        "voice-transformation": "specified",
        "audio-cleanup-master": "runtime_verified",
        "lyria-3-music-generation": "source_built",
        "stable-audio-instrumental-generation": "runtime_verified",
        "song-production": "specified",
        "podcast-jingle-narration": "source_built",
    }
    for capability_id, maturity in expected.items():
        capability = capabilities[capability_id]
        assert capability.owner_batch == "36G"
        assert capability.maturity == maturity
        assert receipt in capability.evidence
    assert capabilities["stock-voice-tts"].external_gates == (
        "synthetic-voice-disclosure",
    )
    assert capabilities["governed-stt-transcript"].external_gates == ()
    assert capabilities["multi-speaker-diarization"].external_gates == ()
    assert capabilities["complete-stock-voice-dubbing"].external_gates == ()
    assert capabilities["voice-transformation"].external_gates == (
        "voice-rights-and-consent-evidence",
    )
    assert capabilities["lyria-3-music-generation"].external_gates == (
        "valid-replicate-credential",
        "lyria-preview-runtime-evidence",
        "music-rights-and-synthid-disclosure",
    )
    assert capabilities["stable-audio-instrumental-generation"].external_gates == (
        "funded-stability-credential",
        "music-rights-and-ai-generated-disclosure",
    )
    assert "SFX" not in capabilities["audio-cleanup-master"].title
    assert capabilities["stt-tts-dubbing"].maturity != "runtime_verified"
    assert capabilities["podcast-jingle-narration"].maturity != "runtime_verified"
    assert capabilities["song-production"].maturity != "runtime_verified"
    assert capabilities["voice-transformation"].maturity != "runtime_verified"
    assert BATCHES[6].status == "in_progress"


def test_phase36_snapshot_is_truthful_and_phase29_is_not_current_finality() -> None:
    snapshot = phase36_program_snapshot()
    assert snapshot["authoritative"] is True
    assert snapshot["minimum_concurrent_users"] == 1000
    assert snapshot["current_batch"] == "36G"
    batch_statuses = {batch["batch_id"]: batch["status"] for batch in snapshot["batches"]}
    assert batch_statuses["36B"] == "complete"
    assert batch_statuses["36C"] == "complete"
    assert batch_statuses["36D"] == "complete"
    assert batch_statuses["36E"] == "complete"
    assert batch_statuses["36F"] == "complete"
    assert batch_statuses["36G"] == "in_progress"
    assert snapshot["total_capabilities"] == len(CAPABILITIES)
    assert snapshot["production_ready_capabilities"] < snapshot["total_capabilities"]
    assert snapshot["completion"] < 100
    assert snapshot["maturity_order"] == list(MATURITY_ORDER)


def test_phase36_reporting_invariant_requires_evidence_for_owned_changes() -> None:
    owned = ["src/aios/full_project_cycle.py"]
    assert phase36_reporting_violation(owned) == tuple(owned)
    audio_owned = [
        "src/aios/audio_factory.py",
        "web-dashboard/backend/app/services/audio_pipeline.py",
        "web-dashboard/backend/app/services/media_ffmpeg.py",
        "web-dashboard/backend/scripts/verify_media_worker.py",
    ]
    assert phase36_reporting_violation(audio_owned) == tuple(sorted(audio_owned))
    assert phase36_reporting_violation(
        [*owned, "docs/phase-36/receipts/36B-example.md"]
    ) == ()
    assert phase36_reporting_violation(
        [*owned, "docs/phase-36/exemptions/example.md"]
    ) == ()
    assert phase36_reporting_violation(["README.md"]) == ()


def test_phase36_reporting_checker_cli_enforces_and_accepts_receipts() -> None:
    checker = ROOT / "scripts/check_phase36_reporting.py"
    blocked = subprocess.run(
        ["python3", str(checker), "--files", "src/aios/full_project_cycle.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 2
    assert "PHASE36_REPORTING_MISSING" in blocked.stderr
    allowed = subprocess.run(
        [
            "python3",
            str(checker),
            "--files",
            "src/aios/full_project_cycle.py",
            "docs/phase-36/receipts/36B-example.md",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert allowed.returncode == 0
    assert "PHASE36_REPORTING_OK" in allowed.stdout


def test_phase36_reporting_docs_and_surfaces_exist() -> None:
    for relative in (
        "docs/phase-36/PHASE_36_UNIVERSAL_CAPABILITY_SCALE_MASTER_ROADMAP.md",
        "docs/phase-36/REPORTING_RECEIPT_TEMPLATE.md",
        "docs/phase-36/receipts/36A-2026-08-17-program-governance.md",
        "web-dashboard/backend/app/api/v1/endpoints/capabilities.py",
        "web-dashboard/frontend/src/app/owner/completion/page.tsx",
        "vip-frontend/src/components/pages/projects-client.tsx",
    ):
        assert (ROOT / relative).is_file(), relative
    capability_source = (ROOT / "web-dashboard/backend/app/api/v1/endpoints/capabilities.py").read_text()
    owner_source = (ROOT / "web-dashboard/backend/app/api/owner/control_plane.py").read_text()
    owner_ui = (ROOT / "web-dashboard/frontend/src/app/owner/completion/page.tsx").read_text()
    user_ui = (ROOT / "vip-frontend/src/components/pages/projects-client.tsx").read_text()
    assert "phase36_program_snapshot" in capability_source
    assert '"phase36": phase36_program_snapshot()' in owner_source
    assert "snapshot.phase36" in owner_ui
    assert "getPhase36Capabilities" in user_ui


def test_phase36b_distributed_worker_scale_assets_are_explicitly_gated() -> None:
    compose_override = (
        ROOT / "deploy/phase36b/docker-compose.project-worker-scale.yml"
    ).read_text(encoding="utf-8")
    cluster_manifest = (
        ROOT / "deploy/phase36b/kubernetes/project-worker.yaml"
    ).read_text(encoding="utf-8")
    receipt = (
        ROOT / "docs/phase-36/receipts/36B-2026-08-17-distributed-project-execution.md"
    ).read_text(encoding="utf-8")
    assert "PROJECT_EXECUTION_WORKER_CAPACITY" in compose_override
    assert "replicas: 2" in compose_override
    assert "kind: Deployment" in cluster_manifest
    assert "kind: HorizontalPodAutoscaler" in cluster_manifest
    assert "aionex-project-execution-rwx" in cluster_manifest
    assert "registry.example.invalid" in cluster_manifest
    assert "External activation gates remaining" in receipt
