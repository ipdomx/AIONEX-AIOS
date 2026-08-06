from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX = (ROOT / "web-dashboard/docker/nginx.conf").read_text(encoding="utf-8")


def test_public_identity_recovery_and_mfa_routes_reach_backend() -> None:
    assert "password-reset(?:/confirm)?" in NGINX
    assert "mfa/challenge/verify" in NGINX
    assert "mfa(?:/.*)?" in NGINX


def test_public_account_session_management_is_allowlisted() -> None:
    assert "settings(?:/(?:password|sessions))?" in NGINX


def test_privileged_identity_administration_remains_private() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    for path in ("teams", "users", "roles", "permissions", "organizations"):
        assert f"|{path}" not in public_server
        assert f"/{path}" not in public_server
