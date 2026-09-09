from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX = (ROOT / "web-dashboard/docker/nginx.conf").read_text(encoding="utf-8")


def test_public_identity_recovery_and_mfa_routes_reach_backend() -> None:
    assert "password-reset(?:/confirm)?" in NGINX
    assert "mfa/challenge" in NGINX
    assert "mfa/challenge/verify" not in NGINX
    assert "mfa(?:/.*)?" in NGINX


def test_public_account_session_management_is_allowlisted() -> None:
    assert (
        "settings(?:/(?:password|sessions(?:/[0-9a-f]{8}-[0-9a-f]{4}-"
        "[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?))?"
        in NGINX
    )


def test_public_session_revoke_path_is_uuid_scoped() -> None:
    assert "sessions(?:/.*)?" not in NGINX
    assert "sessions(?:/[^/]+)?" not in NGINX


def test_privileged_identity_administration_remains_private() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    for path in ("teams", "users", "roles", "permissions", "organizations"):
        assert f"|{path}" not in public_server
        assert f"/{path}" not in public_server


def test_identity_media_provider_input_bridge_is_narrowly_public() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    route = (
        'location ~ "^/api/v1/studio/identity-media/provider-input/'
        '[A-Za-z0-9_-]{20,1900}\\.[0-9a-f]{64}/[A-Za-z0-9._-]{1,160}$"'
    )
    assert public_server.count("studio/identity-media/provider-input") == 1
    assert route in public_server
    block = public_server.split(route, 1)[1].split("\n        }", 1)[0]
    assert "access_log off;" in block
    assert "limit_except GET" in block
    assert "proxy_pass http://$backend_upstream;" in block
    assert "X-AIOS-Auth-Channel public" in block
    assert 'proxy_set_header Authorization "";' in block
    assert 'proxy_set_header Cookie "";' in block
    assert "proxy_buffering off;" in block
    assert public_server.index(route) < public_server.index("location /api/")
    assert "studio/identity-media(?:/.*)?" not in public_server


def test_entitled_security_lab_user_routes_are_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "security-lab(?:/.*)?" in public_server
    assert "owner/security-lab" not in public_server
    assert "X-AIOS-Auth-Channel public" in public_server


def test_user_telegram_linking_routes_are_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "telegram/(?:status|link-challenge|link)" in public_server
    assert "X-AIOS-Auth-Channel public" in public_server


def test_growth_social_access_route_is_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "growth-social/access" in public_server
    assert "owner/growth-social" not in public_server
    assert "X-AIOS-Auth-Channel public" in public_server


def test_growth_campaign_intelligence_routes_are_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "growth-social/access" in public_server
    assert "growth-social/campaigns(?:/.*)?" in public_server
    assert "owner/growth-social" not in public_server
    assert "X-AIOS-Auth-Channel public" in public_server


def test_growth_social_account_registry_routes_are_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "growth-social/accounts(?:/.*)?" in public_server
    assert "growth-social/providers(?:/.*)?" in public_server
    assert "owner/growth-social" not in public_server
    assert "X-AIOS-Auth-Channel public" in public_server


def test_growth_content_operations_routes_are_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "growth-social/content(?:/.*)?" in public_server
    assert "owner/growth-social" not in public_server
    assert "X-AIOS-Auth-Channel public" in public_server


def test_growth_analytics_learning_routes_are_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "growth-social/analytics(?:/.*)?" in public_server
    assert "owner/growth-social" not in public_server
    assert "X-AIOS-Auth-Channel public" in public_server


def test_growth_lead_intelligence_routes_are_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "growth-social/leads(?:/.*)?" in public_server
    assert "growth-social/inbox(?:/.*)?" in public_server
    assert "growth-social/paid-campaigns(?:/.*)?" in public_server
    assert "owner/growth-social" not in public_server
    assert "X-AIOS-Auth-Channel public" in public_server


def test_growth_advanced_integrations_routes_are_public_channel_allowlisted() -> None:
    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    assert "growth-social/integrations(?:/.*)?" in public_server
    assert "growth-social/team-assignments(?:/.*)?" in public_server
    assert "growth-social/reports(?:/.*)?" in public_server
    assert "growth-social/report-runs(?:/.*)?" in public_server
    assert "owner/growth-social" not in public_server
    assert "X-AIOS-Auth-Channel public" in public_server
