from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "web-dashboard" / "frontend" / "src"

DEAD_MARKERS = (
    "This page is under development",
    "coming soon",
    "not implemented",
    'href="#"',
    "onClick={() => {}}",
)

CRITICAL_LIVE_PAGES = (
    "app/ai/usage/page.tsx",
    "app/infrastructure/containers/page.tsx",
    "app/infrastructure/databases/page.tsx",
    "app/infrastructure/kubernetes/page.tsx",
    "app/infrastructure/queues/page.tsx",
    "app/infrastructure/redis/page.tsx",
    "app/infrastructure/servers/page.tsx",
    "app/monitoring/alerts/page.tsx",
    "app/monitoring/events/page.tsx",
    "app/monitoring/logs/page.tsx",
    "app/monitoring/metrics/page.tsx",
    "app/security/audit/page.tsx",
    "app/security/policies/page.tsx",
    "app/security/sessions/page.tsx",
    "app/security/threats/page.tsx",
)


def test_frontend_has_no_dead_surface_markers() -> None:
    findings = []
    for path in FRONTEND.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        for marker in DEAD_MARKERS:
            if marker.lower() in text.lower():
                findings.append(f"{path.relative_to(ROOT)}:{marker}")
    assert findings == []


def test_critical_operational_pages_use_live_clients_not_hardcoded_fixtures() -> None:
    forbidden = (
        "const servers = [",
        "const threats = [",
        "const events = [",
        "const logs = [",
        "const alerts = [",
    )
    for rel in CRITICAL_LIVE_PAGES:
        text = (FRONTEND / rel).read_text(encoding="utf-8")
        assert any(token in text for token in ("opsSecurityServices", "runtimeServices")), rel
        assert all(token not in text for token in forbidden), rel


def test_owner_routes_remain_live_client_bound() -> None:
    owner = FRONTEND / "app" / "owner"
    for page in owner.rglob("page.tsx"):
        text = page.read_text(encoding="utf-8")
        assert "This page is under development" not in text
