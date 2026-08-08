# Batch 6 — Sandbox acceptance and release readiness

This batch closes every repository-controlled release gate for native mobile subscriptions. Real App Store Sandbox and Google Play license-tester transactions are an external acceptance gate and are never fabricated. They run only when App Store Connect / Play Console products, testers and server credentials are supplied to the deployment.

## Local acceptance
- App Store StoreKit 2 purchase, restore, current-entitlement and transaction-update paths are present.
- Google Play Billing purchase, offers/base plans, restore, acknowledgement and server-verification paths are present.
- App Store Server Notifications V2 and Google Play RTDN are idempotent and server-authoritative.
- Renewal, cancellation, grace, retry/hold, expiry, refund/revocation and product upgrade/downgrade reconciliation are covered by deterministic tests.
- Entitlement arbitration prevents a terminated mobile subscription from removing access still granted by another active provider.
- Migration 0012 is tested fresh-up, downgrade and re-upgrade on disposable PostgreSQL.
- Android release is built, linted, shrunk with R8 and device-smoked; iOS source is Linux-validated and prepared for Xcode signing.
- No production deployment, DNS/Cloudflare modification, App Store submission, Play publication or real charge occurs in this batch.

## External sandbox acceptance gate
The release validator reports whether the required external credentials are present without printing them. If absent, the external gate remains `blocked_missing_external_credentials_or_store_configuration`. This is a truthful boundary: a real sandbox purchase cannot be performed without store products/testers/credentials.

## Rollback
1. Keep the prior signed mobile artifacts and previous server image/tag.
2. Roll back application code/image while leaving migration 0012 in place; the added tables/columns are backward-compatible with the preceding runtime.
3. Disable App Store / Google Play mappings from Owner Billing if a store integration must be stopped without affecting Stripe web billing.
4. Do not delete verified purchase/event records during rollback.
5. Restore the candidate after validation and reconcile both stores before re-enabling mappings.
