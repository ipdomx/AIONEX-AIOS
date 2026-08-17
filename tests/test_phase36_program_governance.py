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
    assert BATCHES[0].status == "complete"
    assert BATCHES[1].status == "in_progress"
    assert all(batch.status == "planned" for batch in BATCHES[2:])


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


def test_phase36_snapshot_is_truthful_and_phase29_is_not_current_finality() -> None:
    snapshot = phase36_program_snapshot()
    assert snapshot["authoritative"] is True
    assert snapshot["minimum_concurrent_users"] == 1000
    assert snapshot["current_batch"] == "36B"
    assert snapshot["total_capabilities"] == len(CAPABILITIES)
    assert snapshot["production_ready_capabilities"] < snapshot["total_capabilities"]
    assert snapshot["completion"] < 100
    assert snapshot["maturity_order"] == list(MATURITY_ORDER)


def test_phase36_reporting_invariant_requires_evidence_for_owned_changes() -> None:
    owned = ["src/aios/full_project_cycle.py"]
    assert phase36_reporting_violation(owned) == tuple(owned)
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
