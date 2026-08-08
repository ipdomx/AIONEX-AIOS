# Batch 4 — Store Server Lifecycle Completion

Status: COMPLETE

Implemented authoritative server-side subscription lifecycle for Apple App Store and Google Play without enabling production store credentials or publishing builds.

## Apple
- Official Apple `app-store-server-library` 3.1.2.
- `SignedDataVerifier` validates App Store transaction JWS and App Store Server Notifications V2 using configured Apple root certificates.
- Production/sandbox environment and bundle/app identifiers are enforced by the verifier.
- App Store Server API client supports authoritative subscription reconciliation by original transaction ID.
- Renewal, failed renewal, grace, expiry, refund/revocation, upgrade/downgrade transaction updates are normalized into AIOS purchase/subscription state.

## Google Play
- Google Play Developer API `purchases.subscriptionsv2.get` is authoritative for purchase-token verification.
- Service-account OAuth JWT flow is server-side only.
- Google Pub/Sub push OIDC identity is validated against configured audience and service-account email before RTDN processing.
- RTDN subscription events are replay protected by message ID.
- Purchase tokens are SHA-256 indexed and Fernet-encrypted at rest using the existing AIOS server secret; plaintext tokens are never stored.
- Server acknowledgement occurs only after a verified purchase; Android client skips duplicate acknowledgement when the server already acknowledged it.
- Reconciliation decrypts the stored token only server-side and re-queries Google Play.

## Entitlements
- Store verification must succeed before `MobileStorePurchase.verified` is set.
- Verified active/grace purchases synchronize the mapped AIOS billing plan, limits and entitlements.
- Expired/revoked/on-hold states remove paid entitlements when no other active billing subscription protects access.
- Google cancellation retains access until the paid expiry time while disabling auto-renewal.

## Callbacks
- `POST /api/v1/billing/mobile-store/notifications/app-store`
- `POST /api/v1/billing/mobile-store/notifications/google-play`
- `POST /api/v1/billing/mobile-store/reconcile/{store}`

Store callback payloads are not persisted verbatim. Events persist a digest and minimal sanitized metadata. Processed event IDs are idempotent; failed events can be retried.

## Validation evidence
- Mobile store source/contract suite: 21 passed.
- Backend lifecycle unit tests in dependency-complete backend image: 6 passed.
- Backend image imports Apple server library successfully.
- Android Release + R8 + lint: PASS.
- iOS source validation: PASS.
- Alembic fresh upgrade -> downgrade to 0011 -> upgrade head on disposable PostgreSQL 16: PASS.
- `git diff --check`: PASS.

External sandbox credentials/products and live store acceptance remain intentionally reserved for Batch 6.
