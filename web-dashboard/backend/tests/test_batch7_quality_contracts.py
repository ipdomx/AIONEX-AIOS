from app.api.v1.api import api_router


def test_required_runtime_routes_are_registered():
    paths = {route.path for route in api_router.routes}
    required = {
        "/auth/login",
        "/auth/me",
        "/projects",
        "/tasks",
        "/workflows",
        "/meetings",
        "/reports",
        "/ai/agents",
        "/ai/providers",
        "/notifications",
        "/monitoring/metrics",
        "/security/events",
        "/backups",
        "/integration/health",
    }
    missing = required.difference(paths)
    assert not missing, f"Missing required routes: {sorted(missing)}"


def test_no_duplicate_api_paths_and_methods():
    seen: set[tuple[str, str]] = set()
    for route in api_router.routes:
        methods = getattr(route, "methods", set()) or set()
        for method in methods:
            key = (route.path, method)
            assert key not in seen, f"Duplicate route registration: {key}"
            seen.add(key)
