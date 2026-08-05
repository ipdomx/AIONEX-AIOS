"""Phase 27 owner-controlled VIP portal and pricing contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard" / "backend"
VIP = ROOT / "vip-frontend"
OWNER = ROOT / "web-dashboard" / "frontend"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_portal_has_durable_owner_api_and_safe_asset_boundary() -> None:
    service = source(BACKEND / "app/services/portal_cms.py")
    public_api = source(BACKEND / "app/api/v1/endpoints/portal.py")
    owner_api = source(BACKEND / "app/api/owner/portal.py")
    router = source(BACKEND / "app/api/v1/router.py")
    nginx = source(ROOT / "web-dashboard/docker/nginx.conf")

    assert 'PORTAL_DOMAIN = "portal-cms"' in service
    assert 'ASSET_DOMAIN = "portal-assets"' in service
    assert "DRAFT_RESOURCE" in service
    assert "PUBLISHED_RESOURCE" in service
    assert "publish_portal_draft" in service
    assert "rollback_portal_publication" in service
    assert "MAX_HISTORY" in service
    assert "MAX_CONFIGURATION_BYTES" in service
    assert "PORTAL_ASSET_MAX_BYTES" in service
    assert "_validate_svg" in service
    assert "javascript:" in service
    assert "<script" in service
    assert "custom_javascript" not in service
    assert "custom_css" not in service

    assert '@router.get("/published")' in public_api
    assert '@router.get("/assets/{asset_id}")' in public_api
    assert 'prefix="/owner/portal"' in owner_api
    assert "require_super_owner" in owner_api
    assert '@router.put("/draft")' in owner_api
    assert '@router.post("/publish")' in owner_api
    assert '@router.post("/rollback/{version}")' in owner_api
    assert '@router.post("/assets"' in owner_api
    assert "portal.router" in router
    assert "owner_portal.router" in router

    assert "portal/(?:published|assets/[0-9a-f]{32})" in nginx
    public_server = nginx.split("# Private control plane.", 1)[0]
    assert "/owner/portal" not in public_server


def test_owner_control_covers_brand_theme_content_pricing_and_publication() -> None:
    page = source(OWNER / "src/app/owner/portal/page.tsx")
    client = source(OWNER / "src/lib/owner-portal.ts")
    navigation = source(OWNER / "src/config/owner-navigation.ts")

    for label in (
        "Branding",
        "Theme & Fonts",
        "Navigation",
        "Plans & Pricing",
        "Pages & SEO",
        "Asset Library",
        "Contact, Footer & Notice",
        "Advanced & History",
    ):
        assert label in page
    for operation in (
        "Save draft",
        "Publish",
        "Rollback and publish",
        "Reset draft to defaults",
        "Upload image, icon, logo, or WOFF2 font",
        "Subscription periods",
        "Translation overrides",
        "Background image URL",
        "Social links JSON",
        "Footer columns and links JSON",
    ):
        assert operation in page
    for endpoint in (
        "/owner/portal/draft",
        "/owner/portal/publish",
        "/owner/portal/rollback/",
        "/owner/portal/reset-draft",
        "/owner/portal/assets",
    ):
        assert endpoint in client
    assert 'href: "/owner/portal"' in navigation


def test_static_vip_shell_consumes_owner_configuration_at_runtime() -> None:
    provider = source(
        VIP / "src/components/portal/portal-experience-provider.tsx"
    )
    theme = source(VIP / "src/styles/globals.css")
    home = source(VIP / "src/components/pages/portal-home.tsx")
    pricing = source(VIP / "src/components/pages/pricing-client.tsx")
    contact = source(VIP / "src/components/pages/contact-client.tsx")
    navbar = source(VIP / "src/components/layout/navbar.tsx")
    footer = source(VIP / "src/components/layout/footer.tsx")

    assert "portal/published" in provider
    assert "translation_overrides" in provider
    assert "applyTheme" in provider
    assert "background_image_url" in provider
    assert "document.title" in provider
    assert "favicon_url" in provider
    assert "PortalSectionRenderer" in home
    assert "configuration?.pricing" in pricing
    assert "periods.find" in pricing
    assert "price == null" in pricing
    assert "configuration?.contact" in contact
    assert "configuration.navigation" in navbar
    assert "configuration?.footer" in footer

    for token in (
        "--primary",
        "--secondary",
        "--portal-heading-font",
        "--portal-arabic-font",
        "--portal-background-image",
        "--portal-radius",
        "--portal-max-width",
    ):
        assert token in theme


def test_pricing_and_all_existing_portal_surfaces_are_represented() -> None:
    service = source(BACKEND / "app/services/portal_cms.py")
    expected_pages = (
        '"home": PortalPage(',
        '"about": PortalPage(',
        '"pricing": PortalPage(',
        '"contact": PortalPage(',
        '"privacy": PortalPage(',
        '"terms": PortalPage(',
        '"login": PortalPage(',
        '"register": PortalPage(',
        '"dashboard": PortalPage(',
        '"projects": PortalPage(',
        '"profile": PortalPage(',
    )
    for page in expected_pages:
        assert page in service

    assert '"id": "free"' in service
    assert '"id": "professional"' in service
    assert '"id": "business"' in service
    assert '"enabled": False' in service
    assert '"price": None' in service
    assert '"price": 0' in service
    assert '"monthly"' in service
    assert '"yearly"' in service
    assert "checkout_provider" in service

    pricing_page = VIP / "src/app/[locale]/pricing/page.tsx"
    assert pricing_page.is_file()
    smoke = source(VIP / "scripts/static-smoke-test.mjs")
    assert '"pricing"' in smoke


def test_assets_are_durable_outside_source_and_compose_mounts_the_library() -> None:
    primary = source(ROOT / "web-dashboard/docker-compose.production.yml")
    alternative = source(ROOT / "deploy/production/docker-compose.production.yml")
    entrypoint = source(BACKEND / "scripts/docker-entrypoint.sh")
    config = source(BACKEND / "app/core/config.py")

    for compose in (primary, alternative):
        assert "portal_asset_data:/var/lib/aionex/portal-assets:rw" in compose
        assert "portal_asset_data:" in compose
    assert "PORTAL_ASSET_ROOT" in config
    assert "PORTAL_PUBLIC_API_ORIGIN" in config
    assert "portal_asset_root" in entrypoint
    assert 'install -d -m 0750 -o aionex -g aionex "$portal_asset_root"' in entrypoint
