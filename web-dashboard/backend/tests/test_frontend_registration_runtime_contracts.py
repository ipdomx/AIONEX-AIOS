from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUTH_GATE = (
    REPOSITORY_ROOT
    / "web-dashboard/frontend/src/components/auth/AuthGate.tsx"
)
FIREBASE_PHONE_AUTH = (
    REPOSITORY_ROOT
    / "web-dashboard/frontend/src/lib/firebase-phone-auth.ts"
)


def test_country_inference_uses_locale_region_not_language_code():
    source = AUTH_GATE.read_text(encoding="utf-8")
    assert "new Intl.Locale(normalized).region" in source
    assert 'split("-")' in source
    assert ".slice(1)" in source
    assert "segments.find" not in source


def test_firebase_phone_error_is_actionable_for_cloud_activation():
    source = FIREBASE_PHONE_AUTH.read_text(encoding="utf-8")
    assert "SMS region policy" in source
    assert "Cloud Billing account" in source
    assert "Authorized domains" in source
    assert "Phone verification is not enabled for this project." not in source
