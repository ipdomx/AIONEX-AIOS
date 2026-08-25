from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIP = ROOT / "vip-frontend"
OWNER = ROOT / "web-dashboard/frontend"
BACKEND = ROOT / "web-dashboard/backend"


def test_user_studio_is_a_first_class_authenticated_portal_surface() -> None:
    page = (VIP / "src/app/[locale]/studio/page.tsx").read_text(encoding="utf-8")
    client = (VIP / "src/components/pages/studio-client.tsx").read_text(encoding="utf-8")
    navbar = (VIP / "src/components/layout/navbar.tsx").read_text(encoding="utf-8")
    frame = (VIP / "src/components/layout/site-frame.tsx").read_text(encoding="utf-8")
    projects = (VIP / "src/components/pages/projects-client.tsx").read_text(encoding="utf-8")

    assert "StudioClient" in page
    assert '`/${locale}/studio`' in navbar
    assert "projects|studio|academy|campaigns|profile" in frame
    assert 't("openStudio")' in projects
    for contract in (
        "getStudioHub",
        "createStudioJob",
        "listStudioJobs",
        "listStudioAssets",
        "retryStudioJob",
        "cancelStudioJob",
        "createStudioRevision",
        "downloadStudioAsset",
        "attachStudioAsset",
    ):
        assert contract in client


def test_user_studio_has_six_locale_parity_and_all_phase36m_entry_families() -> None:
    expected_families = {
        "software",
        "prompts",
        "design",
        "image",
        "audio",
        "video",
        "music",
        "threeD",
        "courses",
        "sector",
    }
    baseline_keys: set[str] | None = None
    for locale in ("ar", "en", "fr", "de", "es", "tr"):
        payload = json.loads((VIP / f"src/messages/{locale}.json").read_text(encoding="utf-8"))
        assert payload["nav"]["studio"]
        assert payload["meta"]["studioTitle"]
        assert payload["meta"]["studioDescription"]
        assert payload["projects"]["openStudio"]
        assert set(payload["studio"]["families"]) == expected_families
        keys = set(payload["studio"])
        if baseline_keys is None:
            baseline_keys = keys
        else:
            assert keys == baseline_keys


def test_user_studio_consumes_owner_governance_hub_and_surfaces_runtime_evidence() -> None:
    api = (VIP / "src/lib/studio-api.ts").read_text(encoding="utf-8")
    client = (VIP / "src/components/pages/studio-client.tsx").read_text(encoding="utf-8")
    backend = (BACKEND / "app/api/v1/endpoints/studio.py").read_text(encoding="utf-8")
    service = (BACKEND / "app/services/studio_governance.py").read_text(encoding="utf-8")

    assert 'request("/studio/hub")' in api
    assert '@router.get("/hub")' in backend
    assert "admit_studio_job" in backend
    assert "daily_job_limit" in service
    assert "max_concurrent_jobs" in service
    assert "eligible_plans" in service
    assert "moderation_mode" in service
    for visible_evidence in ("progress", "provider", "cost", "safety"):
        assert f't("{visible_evidence}")' in client


def test_owner_can_govern_studio_without_source_or_environment_edits() -> None:
    page = (OWNER / "src/app/owner/studio-governance/page.tsx").read_text(encoding="utf-8")
    api = (OWNER / "src/lib/owner-studio-governance.ts").read_text(encoding="utf-8")
    studio = (OWNER / "src/app/studio/page.tsx").read_text(encoding="utf-8")
    routes = (BACKEND / "app/api/owner/studio_governance.py").read_text(encoding="utf-8")

    assert 'href="/owner/studio-governance"' in studio
    assert '"/owner/studio-governance"' in api
    assert "require_super_owner" in routes
    for control in (
        "eligible_plans",
        "daily_job_limit",
        "max_concurrent_jobs",
        "max_attempts",
        "moderation_mode",
        "enabled",
    ):
        assert control in page
    assert "updateOwnerStudioCapability" in page


def test_academy_is_a_real_six_locale_user_surface_not_a_dead_studio_redirect() -> None:
    page = (VIP / "src/app/[locale]/academy/page.tsx").read_text(encoding="utf-8")
    client = (VIP / "src/components/pages/academy-client.tsx").read_text(encoding="utf-8")
    api = (VIP / "src/lib/academy-api.ts").read_text(encoding="utf-8")
    studio = (VIP / "src/components/pages/studio-client.tsx").read_text(encoding="utf-8")

    assert "AcademyClient" in page
    assert '`/${locale}/academy`' in studio
    for contract in (
        "listAcademyCourses",
        "createAcademyCourse",
        "listAcademyCoursePackages",
        "createAcademyCoursePackage",
        "reviewAcademyCoursePackage",
        "downloadAcademyCoursePackage",
    ):
        assert contract in api or contract in client
    assert 'permissions.has("academy:read")' in client
    assert 'permissions.has("academy:write")' in client
    assert 'permissions.has("academy:assess")' in client
    assert 'organization.plan' in client
    assert 'supportedLocales = ["ar", "en", "fr", "de", "es", "tr"]' in client

    baseline_keys: set[str] | None = None
    for locale in ("ar", "en", "fr", "de", "es", "tr"):
        payload = json.loads((VIP / f"src/messages/{locale}.json").read_text(encoding="utf-8"))
        assert payload["meta"]["academyTitle"]
        assert payload["meta"]["academyDescription"]
        keys = set(payload["academyUser"])
        assert len(keys) >= 45
        if baseline_keys is None:
            baseline_keys = keys
        else:
            assert keys == baseline_keys


def test_specialized_36m_launch_surfaces_are_truthful_and_fail_closed() -> None:
    service = (BACKEND / "app/services/studio_governance.py").read_text(encoding="utf-8")
    studio_api = (BACKEND / "app/api/v1/endpoints/studio.py").read_text(encoding="utf-8")
    client = (VIP / "src/components/pages/studio-client.tsx").read_text(encoding="utf-8")
    owner_types = (OWNER / "src/lib/owner-studio-governance.ts").read_text(encoding="utf-8")
    owner_page = (OWNER / "src/app/owner/studio-governance/page.tsx").read_text(encoding="utf-8")

    assert '"music-song"' in service
    assert 'runtime_launchable=False' in service
    assert 'activation_reason="external_activation_required"' in service
    assert 'supported_plans=("starter", "professional", "enterprise")' in service
    assert 'required_permissions=("academy:read",)' in service
    assert 'availability_reason = "permission_required"' in service
    assert '@router.get("/sector-packs")' in studio_api
    assert "REFERENCE_SECTOR_PACKS" in studio_api
    assert "createSectorProject" in client
    assert '"domain-blueprint-v3"' in client
    assert 'supported_plans: string[]' in owner_types
    assert 'runtime_launchable: boolean' in owner_types
    assert 'disabled={!supported}' in owner_page


def test_course_factory_has_a_real_permission_gated_vip_academy_surface() -> None:
    page = (VIP / "src/app/[locale]/academy/page.tsx").read_text(encoding="utf-8")
    client = (VIP / "src/components/pages/academy-client.tsx").read_text(encoding="utf-8")
    api = (VIP / "src/lib/academy-api.ts").read_text(encoding="utf-8")
    frame = (VIP / "src/components/layout/site-frame.tsx").read_text(encoding="utf-8")
    governance = (BACKEND / "app/services/studio_governance.py").read_text(encoding="utf-8")

    assert "AcademyClient" in page
    assert "|academy|" in frame
    assert "required_permissions" in governance
    assert "academy:read" in governance
    assert 'permissions.has("academy:write")' in client
    assert 'availability_reason = "permission_required"' in governance
    for contract in (
        "listAcademyCourses",
        "createAcademyCourse",
        "listAcademyCoursePackages",
        "createAcademyCoursePackage",
        "reviewAcademyCoursePackage",
        "downloadAcademyCoursePackage",
    ):
        assert contract in api
        assert contract in client

    baseline_keys: set[str] | None = None
    for locale in ("ar", "en", "fr", "de", "es", "tr"):
        payload = json.loads(
            (VIP / f"src/messages/{locale}.json").read_text(encoding="utf-8")
        )
        assert payload["meta"]["academyTitle"]
        assert payload["meta"]["academyDescription"]
        assert payload["studio"]["availability"]["permission"]
        keys = set(payload["academyUser"])
        if baseline_keys is None:
            baseline_keys = keys
        else:
            assert keys == baseline_keys
