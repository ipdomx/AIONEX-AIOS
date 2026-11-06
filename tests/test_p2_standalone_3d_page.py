"""Source contracts for the standalone portal 3D page (roadmap item 2.1)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIP = ROOT / "vip-frontend"
LOCALES = ("ar", "de", "en", "es", "fr", "tr")

PAGE = (VIP / "src/app/[locale]/3d/page.tsx").read_text(encoding="utf-8")
CLIENT = (VIP / "src/components/pages/three-d-client.tsx").read_text(encoding="utf-8")
VIEWER = (VIP / "src/components/three-d/three-d-viewer.tsx").read_text(encoding="utf-8")
PANEL = (VIP / "src/components/pages/three-d-project-panel.tsx").read_text(encoding="utf-8")
NAVBAR = (VIP / "src/components/layout/navbar.tsx").read_text(encoding="utf-8")
FRAME = (VIP / "src/components/layout/site-frame.tsx").read_text(encoding="utf-8")
LAYOUT = (VIP / "src/app/[locale]/layout.tsx").read_text(encoding="utf-8")
STATIC_SMOKE = (VIP / "scripts/static-smoke-test.mjs").read_text(encoding="utf-8")
SERVER_SMOKE = (VIP / "scripts/smoke-test.mjs").read_text(encoding="utf-8")
INTEGRITY = (VIP / "scripts/check-integrity.mjs").read_text(encoding="utf-8")
ROADMAP = (ROOT / "docs/project/COMPLETION-ROADMAP.md").read_text(encoding="utf-8")


def _keys(value: dict, prefix: str = "") -> set[str]:
    found: set[str] = set()
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        found |= _keys(item, path) if isinstance(item, dict) else {path}
    return found


def test_route_is_a_static_localized_noindex_page() -> None:
    assert "ThreeDClient" in PAGE
    assert 'path: "3d"' in PAGE
    assert "noIndex: true" in PAGE
    # Locale params are generated once by the [locale] layout for the static export.
    assert "generateStaticParams" in LAYOUT
    assert "export function generateStaticParams" not in PAGE
    assert '"3d",' in STATIC_SMOKE
    assert '"/3d",' in SERVER_SMOKE
    assert "src/app/[locale]/3d/page.tsx" in INTEGRITY


def test_navigation_links_the_page_next_to_studio_on_desktop_and_mobile() -> None:
    assert NAVBAR.count("href={`/${locale}/3d`}") == 2
    assert NAVBAR.count('t("threeD")') == 2
    assert NAVBAR.index("/${locale}/studio") < NAVBAR.index("/${locale}/3d")
    assert "profile|3d)" in FRAME


def test_page_uses_existing_api_helpers_and_backend_contract() -> None:
    for helper in (
        "listProjects",
        "getProjectThreeDAccess",
        "listProjectThreeDJobs",
        "createProjectThreeDJob",
        "cancelProjectThreeDJob",
        "clarifyProjectThreeDJob",
        "getProjectThreeDArtifactLinks",
    ):
        assert helper in CLIENT
    assert "fetch(" not in CLIENT
    assert "third_party_terms_version" in CLIENT
    assert "max_texture_size" in CLIENT
    assert "max_input_megabytes" in CLIENT
    assert "monthly_remaining" in CLIENT
    assert "download_url" in CLIENT and "view_url" in CLIENT
    # The backend accepts images only: text-to-3D is disclosed, never submitted.
    assert "create.textBody" in CLIENT
    assert "prompt" not in CLIENT


def test_every_gate_has_an_honest_state() -> None:
    for kind in (
        '"signedOut"',
        '"upgrade"',
        '"serviceDisabled"',
        '"providerUnavailable"',
        '"jurisdiction"',
    ):
        assert kind in CLIENT
    assert "/${locale}/login" in CLIENT
    assert "/${locale}/pricing" in CLIENT
    assert "!value.service_enabled" in CLIENT
    assert "!value.eligible" in CLIENT
    for code in (
        "THREE_D_PROVIDERS_UNAVAILABLE",
        "THREE_D_PROVIDER_CIRCUIT_OPEN",
        "THREE_D_ACCESS_NOT_GRANTED",
        "THREE_D_MONTHLY_QUOTA_REACHED",
        "MEDIA_MAINTENANCE_CLOSED",
    ):
        assert code in CLIENT
    assert "cause.status === 503" in CLIENT
    assert "cause.status === 402" in CLIENT


def test_provider_choice_stays_on_the_server() -> None:
    # Quarantined providers (Hunyuan while HUNYUAN_RUNTIME_SECURITY_APPROVED is
    # False) are filtered by the backend route; the page never offers a picker.
    assert "model_disclosure.model" in CLIENT
    assert "provider:" not in CLIENT
    assert "body.set(\"provider\"" not in CLIENT
    assert not re.search(r"<option[^>]*hunyuan", CLIENT, re.IGNORECASE)


def test_polling_is_bounded_and_visibility_aware() -> None:
    assert "setInterval" not in CLIENT
    assert "window.setTimeout" in CLIENT
    assert "visibilitychange" in CLIENT
    assert 'document.visibilityState === "hidden"' in CLIENT
    assert "POLL_MIN_MS = 4_000" in CLIENT
    assert "POLL_MAX_MS = 30_000" in CLIENT
    assert "POLL_ERROR_MAX_MS" in CLIENT
    assert "pollInFlight" in CLIENT
    assert "cause.status === 401" in CLIENT
    assert "removeEventListener(\"visibilitychange\"" in CLIENT


def test_shared_viewer_orbits_zooms_resets_and_disposes() -> None:
    for token in (
        'from "three"',
        "GLTFLoader",
        "OrbitControls",
        "listenToKeyEvents",
        "stopListenToKeyEvents",
        "reset:",
        "zoom:",
        "controls.dispose()",
        "renderer.dispose()",
        "disposeObject(model)",
        "observer.disconnect()",
        "cancelAnimationFrame",
    ):
        assert token in VIEWER
    assert 'from "@/components/three-d/three-d-viewer"' in PANEL
    assert 'from "@/components/three-d/three-d-viewer"' in CLIENT
    assert "new THREE.WebGLRenderer" not in PANEL


def test_downloads_offer_backend_glb_and_browser_obj() -> None:
    assert "download.glb" in CLIENT
    assert "OBJExporter" in CLIENT
    assert "URL.revokeObjectURL" in CLIENT
    assert "download.objNote" in CLIENT


def test_all_locales_share_the_3d_page_contract_with_arabic() -> None:
    messages = {
        locale: json.loads((VIP / f"src/messages/{locale}.json").read_text(encoding="utf-8"))
        for locale in LOCALES
    }
    reference = _keys(messages["en"]["threeDStudio"])
    used = set(re.findall(r'\bt\("([a-zA-Z.]+)"', CLIENT))
    assert used <= reference, used - reference
    for locale, value in messages.items():
        assert _keys(value["threeDStudio"]) == reference, locale
        assert value["nav"]["threeD"], locale
        assert value["meta"]["threeDTitle"], locale
        assert value["projects"]["threeD"]["resetView"], locale
    arabic = messages["ar"]["threeDStudio"]
    assert re.search(r"[؀-ۿ]", arabic["title"])
    assert re.search(r"[؀-ۿ]", messages["ar"]["nav"]["threeD"])


def test_page_is_accessible_and_rtl_safe() -> None:
    assert 'htmlFor="three-d-image"' in CLIENT
    assert 'htmlFor="three-d-texture"' in CLIENT
    assert 'htmlFor="three-d-project"' in CLIENT
    assert "focus-visible:ring" in CLIENT
    assert 'role="progressbar"' in CLIENT
    assert "aria-pressed" in CLIENT
    assert "text-start" in CLIENT
    for physical in (" ml-", " mr-", " pl-", " pr-", "text-left", "text-right", " left-", " right-"):
        assert physical not in CLIENT
        assert physical not in VIEWER


def test_roadmap_item_is_ticked_pending_live_verification() -> None:
    assert "- [x] 2.1" in ROADMAP
    assert "(code merged; live verification pending)" in ROADMAP
