from pathlib import Path

from aios.phase32_market_readiness import certify_market_readiness

ROOT = Path(__file__).resolve().parents[1]


def test_market_readiness_accepts_truthful_optional_activation_boundaries(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/bin")
    report = certify_market_readiness(
        ROOT,
        running_services=(
            "backup-worker", "communication-worker", "operations-observer",
            "studio-worker", "project-worker", "security-scan-worker",
                "security-remediation-worker", "three-d-worker",
        ),
        configured_env=(),
    )
    assert report.passed
    assert len(report.aggregate_sha256) == 64
    assert all(item.activation_boundary for item in report.findings)


def test_market_readiness_has_no_repository_or_backend_blockers():
    report = certify_market_readiness(
        ROOT,
        running_services=(
            "backup-worker", "communication-worker", "operations-observer",
            "studio-worker", "project-worker", "security-scan-worker",
                "security-remediation-worker", "three-d-worker",
        ),
        configured_env=("TRIPO_API_KEY", "MESHY_API_KEY"),
    )
    blocking = [item for item in report.findings if item.severity in {"high", "critical"}]
    assert blocking == []
