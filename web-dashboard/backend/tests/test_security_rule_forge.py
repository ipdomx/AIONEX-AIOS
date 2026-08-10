from types import SimpleNamespace
from app.services.security_rule_forge import _detector_for, evaluate_detector, validation_corpus


def finding(**kwargs):
    base = {"source": "aionex-headers", "title": "Missing content-security-policy", "category": "security-header", "evidence": {}}
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_missing_header_rule_has_positive_and_negative_fixture():
    _, detector = _detector_for(finding())
    positive, negative = validation_corpus(detector)
    assert evaluate_detector(detector, positive) is True
    assert evaluate_detector(detector, negative) is False


def test_source_marker_detector_does_not_embed_secret_value():
    _, detector = _detector_for(finding(source="aionex-secrets", title="Potential generic secret", category="secret-exposure", evidence={"marker": "generic-secret-assignment", "line": 12}))
    assert detector == {"kind": "source_marker", "marker": "generic-secret-assignment", "category": "secret-exposure"}
    assert evaluate_detector(detector, {"markers": ["generic-secret-assignment"]})
    assert not evaluate_detector(detector, {"markers": []})
