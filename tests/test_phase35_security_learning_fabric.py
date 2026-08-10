from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase35_security_fabric_is_durable_and_owner_controlled():
    models = read("web-dashboard/backend/app/db/models.py")
    for model in (
        "SecurityAccessGrant",
        "SecurityTarget",
        "SecurityScan",
        "SecurityFinding",
        "SecurityRule",
        "SecurityRemediation",
        "SecurityReleaseGate",
    ):
        assert f"class {model}" in models
    owner_api = read("web-dashboard/backend/app/api/owner/security_lab.py")
    assert "require_super_owner" in owner_api
    assert 'router = APIRouter(prefix="/owner/security-lab"' in owner_api


def test_phase35_deep_validation_cannot_be_user_declared_production_clone():
    endpoint = read("web-dashboard/backend/app/api/v1/endpoints/security_lab.py")
    service = read("web-dashboard/backend/app/services/security_fabric.py")
    assert 'Literal["production", "staging"]' in endpoint
    assert 'actor.role != "Super Owner"' in service
    assert 'kind="security_clone"' in service
    assert "re-verify the target before scanning" in service
    assert "public routable addresses" in service


def test_phase35_security_tool_runtime_isolated_from_public_backend():
    compose = read("web-dashboard/docker-compose.production.yml")
    assert "Dockerfile.security-tools" in compose
    assert "aionex-aios-security-tools:local" in compose
    assert 'profiles: ["security-tools"]' in compose
    assert "zaproxy/zap-stable:2.17.0@sha256:" in compose
    zap_section = compose.split("  security-zap:", 1)[1].split("\n  postgres:", 1)[0]
    assert "ports:" not in zap_section
    assert "SECURITY_ZAP_API_KEY" in zap_section
    assert 'cap_drop: ["ALL"]' in compose


def test_phase35_toolchain_and_learning_promotions_are_pinned_and_evidence_gated():
    installer = read("web-dashboard/backend/scripts/install-security-tools.sh")
    for version in (
        "NUCLEI_VERSION=3.11.1",
        "KATANA_VERSION=1.7.0",
        "HTTPX_VERSION=1.10.0",
        "TRIVY_VERSION=0.73.0",
        "OSV_VERSION=2.5.0",
        "SYFT_VERSION=1.50.0",
        "GRYPE_VERSION=0.116.1",
        "GITLEAKS_VERSION=8.30.1",
        "TRUFFLEHOG_VERSION=3.96.0",
        "TESTSSL_VERSION=3.2.4",
        "NIKTO_VERSION=2.6.1",
    ):
        assert version in installer
    rule_forge = read("web-dashboard/backend/app/services/security_rule_forge.py")
    assert 'finding.state != "confirmed"' in rule_forge
    assert 'rule.status != "validated"' in rule_forge
    assert "validation_failures" in rule_forge
    remediation = read("web-dashboard/backend/app/services/security_remediation.py")
    assert '"auto_merge": False' in remediation
    assert '"production_modified": False' in remediation
    assert "requires_security_retest" in remediation


def test_security_worker_has_durable_writable_tool_cache():
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        compose = read(relative)
        section = compose.split("security-scan-worker:", 1)[1].split("security-remediation-worker:", 1)[0]
        assert "read_only: true" in section
        assert "security_tool_cache_data:/tmp/aionex-security-home:rw" in section
        assert "security_tool_cache_data:" in compose


def test_phase35_security_lab_is_exposed_to_entitled_vip_users_in_all_locales():
    assert (ROOT / "vip-frontend/src/app/[locale]/security-lab/page.tsx").is_file()
    client = read("vip-frontend/src/components/pages/security-lab-client.tsx")
    api = read("vip-frontend/src/lib/api.ts")
    navbar = read("vip-frontend/src/components/layout/navbar.tsx")
    dashboard = read("vip-frontend/src/components/pages/dashboard-client.tsx")
    assert "getSecurityLabAccess" in client
    assert "createSecurityScan" in client
    assert "registerExternalSecurityTarget" in client
    assert '"/security-lab/access"' in api
    assert '"/security-lab/scans"' in api
    assert "securityLabVisible" in navbar
    assert "securityAccess?.enabled && securityAccess.granted" in dashboard
    for locale in ("ar", "en", "fr", "de", "es", "tr"):
        messages = read(f"vip-frontend/src/messages/{locale}.json")
        assert '"securityLab"' in messages
        assert '"securityLabTitle"' in messages


def test_security_remediation_worker_bootstraps_only_its_writable_volume():
    entrypoint = read("web-dashboard/backend/scripts/docker-entrypoint.sh")
    assert 'portal_asset_root="${PORTAL_ASSET_ROOT-/var/lib/aionex/portal-assets}"' in entrypoint
    assert 'studio_asset_root="${STUDIO_ASSET_ROOT-/var/lib/aionex/studio-assets}"' in entrypoint
    assert 'mobile_release_root="${MOBILE_RELEASE_ROOT-/var/lib/aionex/mobile-releases}"' in entrypoint
    assert 'security_remediation_root="${SECURITY_REMEDIATION_ROOT:-}"' in entrypoint
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        compose = read(relative)
        section = compose.split("security-remediation-worker:", 1)[1].split("security-zap:", 1)[0]
        assert "SECURITY_REMEDIATION_ROOT: /var/lib/aionex/security-remediations" in section
        assert 'PORTAL_ASSET_ROOT: ""' in section
        assert 'STUDIO_ASSET_ROOT: ""' in section
        assert 'MOBILE_RELEASE_ROOT: ""' in section
        assert 'cap_drop: ["ALL"]' in section
        assert 'cap_add: ["CHOWN", "FOWNER", "SETGID", "SETUID"]' in section
