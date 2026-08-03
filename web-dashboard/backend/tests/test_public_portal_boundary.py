from pathlib import Path

import pytest
from app.core.auth import UserRecord, enforce_auth_channel_role
from fastapi import HTTPException
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[3]


def _user(role: str) -> UserRecord:
    return UserRecord(
        id="user-1",
        email="user@example.com",
        name="Test User",
        role=role,
        password_hash="unused",
        organization_id="org-1",
        organization_name="Test Organization",
        organization_plan="free",
        permissions=[],
    )


def _request(*, channel: str = "", origin: str = "") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if channel:
        headers.append((b"x-aios-auth-channel", channel.encode()))
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def test_public_gateway_rejects_super_owner_without_relying_on_origin() -> None:
    with pytest.raises(HTTPException) as rejected:
        enforce_auth_channel_role(_request(channel="public"), _user("Super Owner"))
    assert rejected.value.status_code == 403


def test_public_portal_origin_rejects_super_owner_as_defense_in_depth() -> None:
    with pytest.raises(HTTPException) as rejected:
        enforce_auth_channel_role(
            _request(origin="https://ai.vip-e.net"), _user("Super Owner")
        )
    assert rejected.value.status_code == 403


def test_private_gateway_allows_super_owner_and_public_gateway_allows_users() -> None:
    enforce_auth_channel_role(_request(channel="private"), _user("Super Owner"))
    enforce_auth_channel_role(_request(channel="public"), _user("Free User"))


@pytest.mark.parametrize("role", ["Free User", "Member", "Engineer", "Admin"])
def test_private_gateway_rejects_every_non_owner_role(role: str) -> None:
    with pytest.raises(HTTPException) as rejected:
        enforce_auth_channel_role(_request(channel="private"), _user(role))
    assert rejected.value.status_code == 403


def test_control_plane_has_no_public_registration_or_seeded_login() -> None:
    auth_gate = (
        ROOT / "web-dashboard/frontend/src/components/auth/AuthGate.tsx"
    ).read_text(encoding="utf-8")
    auth_service = (
        ROOT / "web-dashboard/frontend/src/lib/auth-service.ts"
    ).read_text(encoding="utf-8")
    backend_auth = (
        ROOT / "web-dashboard/backend/app/api/v1/endpoints/auth.py"
    ).read_text(encoding="utf-8")
    assert "registerFree" not in auth_gate + auth_service
    assert "owner@aionex.local" not in auth_gate + auth_service
    assert "NEXT_PUBLIC_USER_PORTAL_URL" in auth_gate
    assert 'user?.role !== "Super Owner"' in auth_gate
    assert '@router.post("/register"' not in backend_auth
