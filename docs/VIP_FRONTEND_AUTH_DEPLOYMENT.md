# VIP frontend authentication release

This release adds the `vip-frontend` Next.js application and the matching AIOS
authentication endpoints for social OAuth/OIDC and WebAuthn passkeys.

## Deployment order

1. Configure the production variables documented in
   `deploy/production/.env.production.example`.
2. Keep the Firebase Admin service-account file outside Git and mount it at the
   configured `FIREBASE_ADMIN_CREDENTIALS_JSON` path.
3. In Firebase Authentication, enable Google, Apple, Facebook and Twitter. Add
   Instagram as the custom OIDC provider `oidc.instagram`.
4. Add `vip-e.net`, `www.vip-e.net` and the deployed AIOS hostname to Firebase
   authorized domains and each provider's callback allowlist.
5. Deploy the backend first. Its container runs `alembic upgrade head`, creating
   `external_identities` and `passkey_credentials` before serving traffic.
6. Build and deploy the production Compose stack. Its `frontend` service now
   builds `vip-frontend` and sends the same-origin `/api/v1` proxy directly to
   the internal `backend:8000` service.

## Security behavior

- Provider secrets never enter the browser or Git repository.
- Firebase ID tokens are verified by the Admin SDK, must contain a verified
  email and recent authentication time, and are exchanged for AIOS sessions.
- The first social sign-in links only to an existing AIOS account with the same
  verified email. New users complete the existing owner-controlled, phone-
  verified registration flow first.
- Passkey challenges are single-use, expire in Redis and require user
  verification. Public keys and signature counters are stored in PostgreSQL;
  private keys remain on the user's authenticator.
- WebAuthn requires HTTPS and an origin listed in `PASSKEY_ALLOWED_ORIGINS`.

## Verification

Run the frontend checks:

```bash
cd vip-frontend
npm ci
npm run verify
npm audit --omit=dev --audit-level=high
```

Run the focused backend checks:

```bash
cd web-dashboard/backend
pytest -q tests/test_social_passkey_auth.py \
  tests/test_firebase_phone_auth.py \
  tests/test_free_registration_identity.py \
  tests/test_database_settings.py
```
