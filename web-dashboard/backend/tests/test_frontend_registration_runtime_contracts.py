from pathlib import Path


# Mobile-browser failures must stay diagnosable without developer tools.
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


def test_mobile_verification_error_is_actionable_without_provider_branding():
    source = FIREBASE_PHONE_AUTH.read_text(encoding="utf-8")
    assert "SMS region policy" in source
    assert "active billing account" in source
    assert "authorized domains" in source
    assert "Phone verification is not enabled for this project." not in source
    assert "Firebase rejected SMS for this project" not in source


def test_mobile_verification_unknown_errors_expose_safe_reference_codes():
    source = FIREBASE_PHONE_AUTH.read_text(encoding="utf-8")
    assert "function firebaseErrorCode" in source
    assert "Reference: ${code}." in source
    assert '"auth/invalid-app-credential"' in source
    assert '"auth/app-not-authorized"' in source
    assert '"auth/invalid-recaptcha-token"' in source
    assert "requests-from-referer" in source
    assert "error.message" in source
