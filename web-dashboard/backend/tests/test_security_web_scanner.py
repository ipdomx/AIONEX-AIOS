from app.services.security_web_scanner import analyze_headers, analyze_tls


def test_missing_headers_are_reported():
    findings = analyze_headers(
        "https://example.com", {"x-content-type-options": "nosniff"}
    )
    titles = {item["title"] for item in findings}
    assert "Missing strict-transport-security" in titles
    assert "Missing content-security-policy" in titles


def test_strong_headers_do_not_emit_missing_header_findings():
    headers = {
        "strict-transport-security": "max-age=31536000; includeSubDomains",
        "content-security-policy": "default-src 'self'; script-src 'self'",
        "x-content-type-options": "nosniff",
        "referrer-policy": "strict-origin-when-cross-origin",
        "permissions-policy": "camera=(), microphone=()",
    }
    findings = analyze_headers("https://example.com", headers)
    assert not [item for item in findings if item["title"].startswith("Missing ")]


def test_plain_http_is_high_severity_transport_finding():
    findings = analyze_tls("http://example.com", None)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert findings[0]["category"] == "transport-security"
