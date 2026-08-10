import pytest
from app.services import security_zap


def test_zap_requires_internal_url_and_key(monkeypatch):
    monkeypatch.delenv("SECURITY_ZAP_URL", raising=False)
    monkeypatch.delenv("SECURITY_ZAP_API_KEY", raising=False)
    assert security_zap.configured() is False
    monkeypatch.setenv("SECURITY_ZAP_URL", "http://security-zap:8080")
    assert security_zap.configured() is False
    monkeypatch.setenv("SECURITY_ZAP_API_KEY", "test-key")
    assert security_zap.configured() is True


def test_zap_alert_normalization_excludes_attack_payloads():
    item = security_zap._finding(
        {
            "pluginId": "10001",
            "alert": "Missing header",
            "risk": "Medium",
            "url": "https://example.test/",
            "param": "q",
            "attack": "SHOULD_NOT_BE_PERSISTED",
            "evidence": "SHOULD_NOT_BE_PERSISTED",
            "solution": "Set the header.",
            "cweid": "693",
        }
    )
    assert item["severity"] == "medium"
    assert item["cwe"] == "CWE-693"
    assert "SHOULD_NOT_BE_PERSISTED" not in str(item)


@pytest.mark.asyncio
async def test_active_zap_is_clone_only(monkeypatch):
    monkeypatch.setenv("SECURITY_ZAP_URL", "http://security-zap:8080")
    monkeypatch.setenv("SECURITY_ZAP_API_KEY", "test-key")
    result = await security_zap.run_zap(
        "https://example.test", execution_mode="passive", active=True
    )
    assert result["status"] == "blocked_requires_clone"
