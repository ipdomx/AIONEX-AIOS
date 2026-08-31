from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "web-dashboard/docker-compose.production.yml"
NGINX = ROOT / "web-dashboard/docker/nginx.conf"
NEXT_CONFIG = ROOT / "web-dashboard/frontend/next.config.mjs"
BACKEND_MAIN = ROOT / "web-dashboard/backend/main.py"
PREFLIGHT = ROOT / "web-dashboard/scripts/validate-private-origin.sh"
RUNBOOK = ROOT / "web-dashboard/PRIVATE_ORIGIN_DEPLOYMENT.md"


def test_origin_and_data_services_are_not_publicly_exposed():
    source = COMPOSE.read_text(encoding="utf-8")
    assert '"127.0.0.1:${AIOS_ORIGIN_PORT:-8080}:8080"' in source
    assert '"127.0.0.1:${AIOS_CONTROL_PORT:-8081}:8081"' in source
    assert '"127.0.0.1:${AIOS_PORTAL_PORT:-8082}:8082"' in source
    assert "context: ../vip-frontend" in source
    assert "cloudflare/cloudflared" in source
    assert 'profiles: ["tunnel"]' in source
    assert "CLOUDFLARE_TUNNEL_TOKEN" in source
    assert "5432:5432" not in source
    assert "6379:6379" not in source
    assert "8000:8000" not in source
    assert "3000:3000" not in source


def test_gateway_enforces_headers_limits_and_private_docs():
    source = NGINX.read_text(encoding="utf-8")
    for required in (
        "server_tokens off",
        "limit_req_zone",
        "X-Robots-Tag",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Strict-Transport-Security",
        "client_max_body_size",
        "openapi\\.json",
        "listen 8080",
        "listen 8081",
        "listen 8082",
        "Public user portal origin",
        "X-AIOS-Auth-Channel public",
        "X-AIOS-Auth-Channel private",
        "Only contracts used by the public user portal",
        "location /api/",
        "return 404",
    ):
        assert required in source


def test_frontend_does_not_publish_source_maps_and_has_csp():
    source = NEXT_CONFIG.read_text(encoding="utf-8")
    assert "productionBrowserSourceMaps: false" in source
    assert "poweredByHeader: false" in source
    assert "Content-Security-Policy" in source
    assert "frame-ancestors 'none'" in source
    assert "Strict-Transport-Security" in source


def test_backend_requires_explicit_production_hosts_and_hides_details():
    source = BACKEND_MAIN.read_text(encoding="utf-8")
    assert 'os.getenv("AIOS_ALLOWED_HOSTS"' in source
    assert "Production host policy is not configured" in source
    assert "Untrusted host" in source
    assert "allow_methods=[\"GET\", \"POST\", \"PUT\", \"PATCH\", \"DELETE\", \"OPTIONS\"]" in source
    assert '"environment": settings.ENVIRONMENT' not in source
    assert "server_header=False" in source


def test_deployment_preflight_rejects_wildcards_and_weak_secrets():
    source = PREFLIGHT.read_text(encoding="utf-8")
    assert "AIOS_ALLOWED_HOSTS is required" in source
    assert "AIOS_CONTROL_HOST is required" in source
    assert "AIOS_CONTROL_HOST must be the private Cloudflare Access hostname" in source
    assert "AIOS_ALLOWED_HOSTS must include AIOS_CONTROL_HOST" in source
    assert "AIOS_PUBLIC_PORTAL_ORIGINS must include AIOS_USER_PORTAL_URL" in source
    assert "CORS_ORIGINS cannot contain wildcard" in source
    assert "SECRET_KEY must contain at least 32 characters" in source
    assert "possible committed secret detected" in source
    assert "public production source maps are enabled" in source


def test_runbook_states_external_owner_actions_without_false_guarantees():
    source = RUNBOOK.read_text(encoding="utf-8")
    assert "Browser code is inherently inspectable" in source
    assert "block public inbound TCP 80/443" in source
    assert "Make the GitHub repository private" in source
    assert "rotate every credential" in source
    assert "Repository code cannot create" in source
