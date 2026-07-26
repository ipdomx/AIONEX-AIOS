from fastapi import HTTPException

from app.core.auth import auth_service


def test_invalid_password_is_rejected():
    try:
        auth_service.authenticate("owner@aionex.local", "wrong-password")
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Invalid credentials were accepted")


def test_refresh_token_rotation_rejects_reuse():
    user = auth_service.authenticate("owner@aionex.local", "ChangeMeNow!123")
    pair = auth_service.issue_pair(user)
    rotated = auth_service.refresh(pair["refresh_token"])
    assert rotated["access_token"] != pair["access_token"]
    try:
        auth_service.refresh(pair["refresh_token"])
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("A rotated refresh token was reused")


def test_revoked_access_token_is_rejected():
    user = auth_service.authenticate("owner@aionex.local", "ChangeMeNow!123")
    token = auth_service.create_access_token(user)
    auth_service.revoke_access_token(token)
    try:
        auth_service.decode_access_token(token)
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("A revoked access token remained valid")
