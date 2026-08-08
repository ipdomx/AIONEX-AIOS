# AIONEX AIOS Mobile Store Billing Plan

## Goal
Complete compliant native subscription billing for both mobile stores while preserving existing Stripe Checkout + Apple Pay/Google Pay for web/PWA.

## Batch 1 — Store billing foundation (this batch)
- Define a single provider-neutral mobile store contract for App Store and Google Play subscriptions.
- Persist store products, purchase receipts/tokens, subscription lifecycle state, and idempotent notification events.
- Add backend configuration for App Store and Google Play server verification credentials and package/bundle identifiers.
- Add authenticated mobile billing endpoints for product catalogue, purchase verification, restore/sync, and subscription status.
- Add tests proving entitlement state cannot be granted from an unverified client assertion.
- No production secrets, store product creation, Cloudflare/DNS changes, or deployment.

## Batch 2 — iOS StoreKit 2 client
- Add StoreKit 2 product loading, purchase, restore purchases, current entitlements, transaction listener, and signed transaction submission to AIOS.
- Add native subscription UI bridge so the iOS app does not route digital subscription purchases to Stripe Checkout.
- Preserve Stripe/Apple Pay for web/PWA and eligible external web flows only.
- Add iOS source validation tests on Linux; final signed StoreKit sandbox test remains dependent on Apple/Xcode environment.

## Batch 3 — Google Play Billing client ✅ COMPLETE
- Add the current Google Play Billing Library, ProductDetails, subscription offer/base-plan handling, purchase flow, restore/query purchases, acknowledgement coordination, and secure token submission to AIOS.
- Add native subscription UI bridge so the Play-distributed Android app does not route digital subscriptions to Stripe Checkout.
- Add Android unit/source tests and emulator/device smoke coverage.

## Batch 4 — Store server lifecycle ✅ COMPLETE
- Integrate App Store Server API / signed transaction verification and App Store Server Notifications V2.
- Integrate Google Play Developer API verification and Real-time Developer Notifications.
- Reconcile renewal, cancellation, expiration, grace, billing retry/hold, refund/revocation, upgrade/downgrade and restore states into the existing AIOS billing account and entitlements.
- Add replay protection, idempotency, audit records and reconciliation jobs.

## Batch 5 — Owner control, catalogue mapping and UX ✅ COMPLETE
- Add owner-side mapping between AIOS plans/periods and App Store product IDs / Google Play subscription IDs + base plans/offers.
- Add readiness diagnostics for missing store configuration.
- Add localized billing/restore/manage-subscription UI and clear provider/source labels.
- Keep web Stripe subscriptions interoperable with mobile entitlements without duplicate access grants.

## Batch 6 — Sandbox acceptance and production release readiness
- Configure external sandbox products/credentials only when supplied/authorized.
- Run App Store Sandbox and Google Play license-tester end-to-end flows.
- Validate purchase, renewal, cancellation, restore, refund/revocation, upgrade/downgrade and account entitlement sync.
- Run complete backend/mobile regression suites, migration upgrade/downgrade tests, security checks, release evidence and rollback plan.
- Production/store publication remains a separate explicit authorization step.

## Store-policy baseline
- Apple digital subscriptions inside an App Store app use In-App Purchase / StoreKit except where a current storefront-specific entitlement or rule permits an external purchase path.
- Google Play digital subscriptions use Google Play Billing unless a current eligible alternative-billing program applies.
- Server-side verification is authoritative; the client never grants AIOS subscription entitlements by itself.
