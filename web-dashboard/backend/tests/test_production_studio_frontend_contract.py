from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "web-dashboard/frontend/src/app/studio/page.tsx"
SHELL = ROOT / "web-dashboard/frontend/src/components/layout/DashboardShell.tsx"
ROUTER = ROOT / "web-dashboard/backend/app/api/v1/router.py"


def test_studio_is_visible_and_has_dedicated_department_choices():
    source = PAGE.read_text(encoding="utf-8")
    for label in (
        "Website Studio",
        "Code Studio",
        "UI/UX Studio",
        "3D & Three.js",
        "Video Studio",
        "Animation Studio",
        "Advertising Studio",
        "Documentary Studio",
        "Image Studio",
        "Branding Studio",
    ):
        assert label in source
    assert 'fetch("/api/v1/studio/generate"' in source
    assert "Generate & Download ZIP" in source


def test_production_studio_has_persistent_navigation_entry():
    source = SHELL.read_text(encoding="utf-8")
    assert 'href="/studio"' in source
    assert "Production Studio" in source


def test_studio_api_is_registered_without_enterprise_only_restriction():
    source = ROUTER.read_text(encoding="utf-8")
    assert 'api_router.include_router(studio.router, prefix="/studio"' in source
    assert "dependencies=restricted" not in source.split('api_router.include_router(studio.router', 1)[1].split("\n", 1)[0]
