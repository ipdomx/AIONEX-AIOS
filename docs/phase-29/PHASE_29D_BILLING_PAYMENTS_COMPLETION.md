# Phase 29D — Billing, Licensing, Payments, and Entitlements

## Completion scope

Phase 29D establishes one durable commercial source of truth for public pricing, organization plans, seats, limits, entitlements, metering, wallets, subscriptions, checkout, invoices, transactions, refunds, taxes, coupons, licenses, verified webhooks, provider readiness, and reconciliation.

## Durable data plane

Alembic revision `20260806_0008` and the relational billing models provide retained, tenant-scoped records for:

- plans and subscription periods;
- organization billing accounts and seat limits;
- subscriptions and checkout sessions;
- invoices, transactions, payment methods and refunds;
- coupons, redemptions and tax rates;
- usage records, wallets and immutable wallet entries;
- hashed one-time license keys;
- signed webhook events and reconciliation runs.

No full card number, security code, provider secret, access token, or raw credential is stored in billing records.

## Catalogue and entitlement agreement

The published Owner Portal pricing configuration is synchronized into the billing catalogue. The public pricing page and authenticated billing page read that catalogue, while project, workspace, seat and user creation enforce the same account limits and entitlement state. Free accounts retain the Owner-configured free-tier policy as an explicit overlay.

## Payment lifecycle

- Online checkout supports Stripe, PayPal and Paddle only when the required sandbox or live credentials and provider price references are configured.
- External provider activation and live sandbox credential proof, including Paymob, Fawry, STC Pay and any additional hosted adapter, remain explicitly registered in final provider batch 29J as requested; 29D does not advertise an unproven local checkout.
- Stripe exposes Apple Pay and Google Pay through automatic payment methods.
- Manual invoice and configured bank-transfer checkout return non-secret payment instructions and require Owner settlement before access activates.
- Idempotency keys protect checkout, wallet, usage and refund writes.
- Coupon reservations are counted once and released when checkout fails or expires.
- Country tax rates are calculated in minor currency units.
- Provider cancellation is requested before local subscription state changes.
- Verified and replay-safe webhooks activate access, settle invoices and synchronize safe payment-method metadata.
- Refunds are bounded by the refundable transaction balance and retained in the ledger.

## Owner and user surfaces

The protected Owner Billing Authority controls accounts, plans, seats, suspension, wallets, usage, offline settlement, refunds, coupons, taxes, licenses, providers, webhooks and reconciliation. The user portal exposes current plan, limits, usage, entitlements, invoices, payment methods, provider portal, cancellation, coupon validation and checkout.

## Verification evidence

- `web-dashboard/backend/tests/test_phase29d_billing_payments.py`
- `web-dashboard/backend/app/services/billing.py`
- `web-dashboard/backend/app/api/v1/endpoints/billing.py`
- `web-dashboard/backend/alembic/versions/20260806_0008_billing_payments.py`
- `web-dashboard/frontend/src/app/owner/billing/page.tsx`
- `vip-frontend/src/components/pages/billing-client.tsx`
- `vip-frontend/src/components/pages/pricing-client.tsx`

The completion gate requires a clean migration from the initial schema, the full isolated backend suite, both frontend production builds, GitHub protected checks, a protected production backup, live acceptance without external paid-provider calls, and cleanup of every temporary acceptance record.
