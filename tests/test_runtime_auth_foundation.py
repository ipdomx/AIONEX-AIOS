from pathlib import Path


def test_backend_auth_service_exists() -> None:
    path = Path("web-dashboard/backend/app/core/auth.py")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "class AuthService" in content
    assert "create_access_token" in content
    assert "create_refresh_token" in content


def test_auth_endpoints_are_not_mocked() -> None:
    content = Path("web-dashboard/backend/app/api/v1/endpoints/auth.py").read_text(encoding="utf-8")
    assert "mock_token" not in content
    assert "auth_service.authenticate" in content
    assert "auth_service.refresh" in content


def test_frontend_auth_provider_is_wired() -> None:
    layout = Path("web-dashboard/frontend/src/app/layout.tsx").read_text(encoding="utf-8")
    assert "AuthProvider" in layout
    assert "<AuthProvider>" in layout


def test_api_client_supports_refresh() -> None:
    content = Path("web-dashboard/frontend/src/lib/api-client.ts").read_text(encoding="utf-8")
    assert "refreshAccessToken" in content
    assert "aionex.refresh_token" in content
