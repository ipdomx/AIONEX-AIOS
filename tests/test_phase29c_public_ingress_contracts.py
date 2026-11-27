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
        "settings(?:/(?:password|account/delete|sessions(?:/[0-9a-f]{8}-[0-9a-f]{4}-"
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
    assert "error_log /dev/null crit;" in block
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


def _public_portal_route() -> "re.Pattern[str]":
    import re

    public_server = NGINX.split("# Public user portal origin.", 1)[0]
    marker = 'location ~ "^/api/v1/(?:auth/(?:logout|me|'
    line = public_server[public_server.index(marker):].split("\n", 1)[0]
    return re.compile(line.split('"', 1)[1].rsplit('"', 1)[0])


def test_studio_and_academy_user_routes_reach_the_backend_narrowly() -> None:
    route = _public_portal_route()
    uuid = "0f8b3c2e-1d4a-4b6c-9e7f-123456789abc"
    allowed = [
        "/api/v1/studio/hub",
        "/api/v1/studio/sector-packs",
        "/api/v1/studio/departments",
        "/api/v1/studio/jobs",
        f"/api/v1/studio/jobs/{uuid}",
        f"/api/v1/studio/jobs/{uuid}/cancel",
        f"/api/v1/studio/jobs/{uuid}/retry",
        "/api/v1/studio/assets",
        f"/api/v1/studio/assets/{uuid}",
        f"/api/v1/studio/assets/{uuid}/download",
        f"/api/v1/studio/assets/{uuid}/revisions",
        f"/api/v1/studio/assets/{uuid}/attach",
        "/api/v1/academy/courses",
        f"/api/v1/academy/courses/{uuid}/packages",
        f"/api/v1/academy/packages/{uuid}",
        f"/api/v1/academy/packages/{uuid}/review",
        f"/api/v1/academy/packages/{uuid}/download",
    ]
    blocked = [
        # Runs the worker inside the request.
        "/api/v1/studio/generate",
        # Identity media stays private except for the provider-input bridge.
        "/api/v1/studio/identity-media/capabilities",
        "/api/v1/studio/identity-media/executions",
        "/api/v1/studio/live-media/sessions",
        f"/api/v1/studio/assets/{uuid}/media-graphs",
        f"/api/v1/studio/assets/{uuid}/editable-source",
        f"/api/v1/studio/assets/{uuid}/attach/{uuid}",
        "/api/v1/studio/statistics",
        "/api/v1/studio/jobs/../../owner/studio",
        f"/api/v1/academy/packages/{uuid}/teacher/answer-key",
        f"/api/v1/academy/packages/{uuid}/site/index.html",
        "/api/v1/academy/enrollments",
        "/api/v1/owner/studio-governance",
    ]
    for path in allowed:
        assert route.fullmatch(path), path
    for path in blocked:
        assert not route.fullmatch(path), path


def test_store_purchase_user_routes_reach_the_backend_narrowly() -> None:
    """P-07: in-app purchases are verified by the server; owner mappings and store callbacks stay off this channel."""
    route = _public_portal_route()
    allowed = [
        "/api/v1/billing/mobile-store/readiness",
        "/api/v1/billing/mobile-store/subscription",
        "/api/v1/billing/mobile-store/verify",
        "/api/v1/billing/mobile-store/catalog/app_store",
        "/api/v1/billing/mobile-store/catalog/google_play",
        "/api/v1/billing/mobile-store/restore/google_play",
        "/api/v1/billing/mobile-store/reconcile/app_store",
    ]
    blocked = [
        "/api/v1/billing/mobile-store/owner/overview",
        "/api/v1/billing/mobile-store/owner/mappings",
        "/api/v1/billing/mobile-store/notifications/app-store",
        "/api/v1/billing/mobile-store/notifications/google-play",
        "/api/v1/billing/mobile-store/catalog/other_store",
        "/api/v1/billing/mobile-store/verify/extra",
        "/api/v1/billing/mobile-store/catalog/../owner/overview",
    ]
    for path in allowed:
        assert route.fullmatch(path), path
    for path in blocked:
        assert not route.fullmatch(path), path
