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
