#!/usr/bin/env bash
set -Eeuo pipefail

archive=/tmp/aionex-firebase-overlay.tar.gz
: > "$archive"
for blob in \
  92fd1682e0bae234e5a1ed4191ffbb75acd4c9e7 \
  66366f8daf7490057a250df3ced7f2a9fd218ffe \
  1d6f68585e4ef309b91afc056451d0e4c23fd7ac \
  9629aa5e2da703803e5adf8f400acf6ab7dd6d6a \
  8c56e10e2fd70c34451e254448261e1460d36280
do
  curl --fail --silent --show-error --location \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/git/blobs/${blob}" \
    | jq -r '.content' \
    | tr -d '\r\n ' \
    | base64 --decode >> "$archive"
done

echo "401449922759153d3a289dbcdd295fbed3e69cf3c4d358c36255d86d9f412164  $archive" \
  | sha256sum --check --strict
test "$(tar -tzf "$archive" | wc -l)" = "22"
tar -xzf "$archive" -C "$GITHUB_WORKSPACE"

sed -i -E 's/^firebase-admin==7\.5\.0$/firebase-admin>=6.5,<8/' \
  web-dashboard/backend/requirements.txt
grep -qx 'firebase-admin>=6.5,<8' web-dashboard/backend/requirements.txt
git rm -f --ignore-unmatch web-dashboard/secrets/.gitkeep
chmod 0755 web-dashboard/backend/scripts/docker-entrypoint.sh

python - <<'PY'
from pathlib import Path

path = Path("web-dashboard/backend/app/services/firebase_phone.py")
text = path.read_text()

if "def verify_firebase_phone_token(" not in text:
    text += r'''


def _compat_firebase_app() -> Any:
    """Initialize the Firebase Admin app from the protected AIOS credential source."""

    import json
    import os
    from pathlib import Path

    import firebase_admin
    from fastapi import HTTPException, status
    from firebase_admin import credentials

    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    configured = os.getenv("FIREBASE_ADMIN_CREDENTIALS_JSON", "").strip()
    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    if not configured or not project_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase phone verification is not configured",
        )
    if configured.startswith("{"):
        try:
            source: dict[str, Any] | str = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase Admin credentials JSON is invalid",
            ) from exc
    else:
        credential_path = Path(configured)
        if not credential_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase Admin credentials file is unavailable",
            )
        source = str(credential_path)
    try:
        return firebase_admin.initialize_app(
            credentials.Certificate(source),
            options={"projectId": project_id},
        )
    except ValueError:
        return firebase_admin.get_app()


def verify_firebase_phone_token(id_token: str, expected_phone: str) -> dict[str, Any]:
    """Verify a recent, non-revoked Firebase phone ID token for one E.164 number."""

    import os
    from datetime import UTC, datetime, timedelta

    from fastapi import HTTPException
    from firebase_admin import auth

    if not id_token or len(id_token) < 100:
        raise HTTPException(status_code=422, detail="Invalid Firebase ID token")
    try:
        claims = auth.verify_id_token(
            id_token,
            app=_compat_firebase_app(),
            check_revoked=True,
            clock_skew_seconds=30,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Firebase phone verification failed",
        ) from exc

    phone = str(claims.get("phone_number") or "").strip()
    firebase_claim = claims.get("firebase")
    provider = (
        firebase_claim.get("sign_in_provider")
        if isinstance(firebase_claim, dict)
        else None
    )
    try:
        authenticated_at = datetime.fromtimestamp(int(claims.get("auth_time")), tz=UTC)
    except (TypeError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Firebase token has no valid auth time",
        ) from exc

    now = datetime.now(UTC)
    max_age_seconds = int(os.getenv("FIREBASE_PHONE_TOKEN_MAX_AGE_SECONDS", "600"))
    if (
        phone != expected_phone
        or provider != "phone"
        or authenticated_at > now + timedelta(seconds=30)
        or now - authenticated_at > timedelta(seconds=max_age_seconds)
    ):
        raise HTTPException(
            status_code=422,
            detail="A recent Firebase verification for this phone number is required",
        )
    return claims
'''

if "def issue_aios_phone_assertion(" not in text:
    text += r'''


def issue_aios_phone_assertion(claims: dict[str, Any], phone_number: str) -> str:
    """Convert verified Firebase claims into a short-lived signed AIOS assertion."""

    import base64
    import hashlib
    import hmac
    import json
    import os
    from datetime import UTC, datetime, timedelta

    from fastapi import HTTPException, status

    secret = os.getenv("AIOS_PHONE_VERIFICATION_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AIOS phone verification secret is not configured",
        )
    payload = {
        "phone_number": phone_number,
        "verified": True,
        "line_type": "mobile",
        "provider": "firebase",
        "firebase_uid": str(claims.get("uid") or claims.get("sub") or ""),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{encoded}.{encoded_signature}"
'''

path.write_text(text)
PY

grep -q '^def verify_firebase_phone_token' \
  web-dashboard/backend/app/services/firebase_phone.py
grep -q '^def issue_aios_phone_assertion' \
  web-dashboard/backend/app/services/firebase_phone.py

cd web-dashboard/backend
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m isort \
  app/api/v1/endpoints/auth.py \
  app/api/v1/endpoints/firebase_phone.py \
  app/core/config.py \
  app/services/firebase_phone.py \
  app/services/free_tier.py \
  tests/test_batch7_quality_contracts.py \
  tests/test_firebase_phone_auth.py \
  tests/test_free_registration_identity.py
python -m black --target-version py311 \
  app/api/v1/endpoints/auth.py \
  app/api/v1/endpoints/firebase_phone.py \
  app/core/config.py \
  app/services/firebase_phone.py \
  app/services/free_tier.py \
  tests/test_batch7_quality_contracts.py \
  tests/test_firebase_phone_auth.py \
  tests/test_free_registration_identity.py
python -m ruff check \
  app/api/v1/endpoints/auth.py \
  app/api/v1/endpoints/firebase_phone.py \
  app/core/config.py \
  app/services/firebase_phone.py \
  app/services/free_tier.py \
  tests/test_batch7_quality_contracts.py \
  tests/test_firebase_phone_auth.py \
  tests/test_free_registration_identity.py
python -m compileall app main.py
python -m pytest -vv \
  tests/test_firebase_phone_auth.py \
  tests/test_free_registration_identity.py \
  tests/test_batch7_quality_contracts.py \
  --maxfail=1 --tb=long --showlocals
cd ../frontend
npm install firebase@12.16.0 --save-exact --package-lock-only --ignore-scripts
npm ci
npx prettier --write \
  package.json package-lock.json \
  src/components/auth/AuthGate.tsx \
  src/lib/auth-service.ts \
  src/lib/firebase-phone-auth.ts
npx prettier --check \
  package.json package-lock.json \
  src/components/auth/AuthGate.tsx \
  src/lib/auth-service.ts \
  src/lib/firebase-phone-auth.ts
npm run lint -- \
  --file src/components/auth/AuthGate.tsx \
  --file src/lib/auth-service.ts \
  --file src/lib/firebase-phone-auth.ts
npm run type-check
npm run build
cd ../..

AIOS_ENV_FILE="$GITHUB_WORKSPACE/web-dashboard/.env.production.example" \
  docker compose --env-file web-dashboard/.env.production.example \
    -f web-dashboard/docker-compose.production.yml config --quiet
AIOS_ENV_FILE="$GITHUB_WORKSPACE/deploy/production/.env.production.example" \
  docker compose --env-file deploy/production/.env.production.example \
    -f deploy/production/docker-compose.production.yml config --quiet
docker compose -f web-dashboard/docker-compose.yml config --quiet

test -f web-dashboard/secrets/.gitignore
test "$(find web-dashboard/secrets -mindepth 1 -maxdepth 1 -type f ! -name .gitignore | wc -l)" = "0"
test -z "$(git ls-files 'web-dashboard/secrets/*' | grep -v '^web-dashboard/secrets/.gitignore$' || true)"
if git grep -I -n -E 'BEGIN PRIVATE KEY|"private_key"[[:space:]]*:' -- \
  ':!web-dashboard/backend/tests/*'
then
  exit 1
fi

rm -f .github/workflows/one-shot-firebase-source-snapshot.yml
rm -f .github/workflows/finalize-firebase-integration.yml
rm -f .github/workflows/finalize-firebase-otp-integration.yml
rm -f .github/workflows/finalize-firebase-otp-v2.yml
rm -f .github/scripts/finalize-firebase-otp.sh

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
git diff --cached --check
test -n "$(git diff --cached --name-only)"
git commit -m "Integrate Firebase phone OTP verification"
git push origin "HEAD:${TARGET_BRANCH}"
