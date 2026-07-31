#!/usr/bin/env bash
set -Eeuo pipefail

python - <<'PY'
from pathlib import Path

path = Path("web-dashboard/backend/app/services/free_tier.py")
text = path.read_text()
if "def verify_phone_verification_token(" not in text:
    marker = "\ndef _age_on("
    if marker not in text:
        raise SystemExit("free-tier age helper marker was not found")
    compatibility = r'''

def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid phone verification token",
        ) from exc


def verify_phone_verification_token(
    token: str,
    phone_number: str,
) -> dict[str, Any]:
    """Validate a legacy signed phone assertion.

    Earlier AIOS deployments exchanged a verified provider token for a short-lived
    HMAC assertion before registration. New registrations verify Firebase ID tokens
    directly, but this validator remains available for backward-compatible callers
    during a safe rolling upgrade.
    """

    secret = os.getenv("AIOS_PHONE_VERIFICATION_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Phone verification provider is not configured",
        )

    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload_bytes = _b64url_decode(encoded_payload)
        signature = _b64url_decode(encoded_signature)
        expected = hmac.new(
            secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(payload_bytes)
        if not isinstance(payload, dict):
            raise TypeError("phone assertion payload must be an object")
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid phone verification token",
        ) from exc

    expires_at = _as_utc(payload.get("expires_at"))
    line_type = str(payload.get("line_type") or "").strip().lower()
    blocked_types = {
        "voip",
        "virtual",
        "fixed_voip",
        "landline",
        "toll_free",
        "premium",
        "unknown",
    }
    if (
        payload.get("phone_number") != phone_number
        or payload.get("verified") is not True
        or line_type != "mobile"
        or line_type in blocked_types
        or expires_at is None
        or expires_at <= _now()
        or not str(payload.get("provider") or "").strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="A currently verified real mobile number is required",
        )

    payload["line_type"] = line_type
    return payload

'''
    text = text.replace(marker, compatibility + marker, 1)
    path.write_text(text)

path = Path("web-dashboard/backend/app/services/firebase_phone.py")
text = path.read_text()
if "def _firebase_app(" not in text:
    marker = "\ndef verify_firebase_phone_token("
    if marker not in text:
        raise SystemExit("Firebase compatibility verifier marker was not found")
    alias = r'''

def _firebase_app() -> Any:
    """Backward-compatible Firebase app hook for verified-token callers."""

    return _compat_firebase_app()

'''
    text = text.replace(marker, alias + marker, 1)
text = text.replace("app=_compat_firebase_app(),", "app=_firebase_app(),")
path.write_text(text)
PY

cd web-dashboard/backend
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m black --target-version py311 \
  app/services/free_tier.py \
  app/services/firebase_phone.py
python -m ruff check \
  app/services/free_tier.py \
  app/services/firebase_phone.py
python -m compileall app main.py
python -m pytest -vv \
  tests/test_firebase_phone.py \
  tests/test_firebase_phone_auth.py \
  tests/test_free_registration_identity.py \
  tests/test_batch7_quality_contracts.py \
  --maxfail=1 --tb=long --showlocals
cd ../..

rm -f .github/scripts/finalize-firebase-otp.sh

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
git diff --cached --check
test -n "$(git diff --cached --name-only)"
git commit -m "Restore Firebase phone compatibility contracts"
git push origin "HEAD:${TARGET_BRANCH}"
