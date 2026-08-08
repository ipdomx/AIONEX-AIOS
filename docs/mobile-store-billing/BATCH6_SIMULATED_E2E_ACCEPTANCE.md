# Batch 6 — Simulated Store E2E Acceptance

Status: **COMPLETE** (2026-08-09)

This acceptance run intentionally uses deterministic simulated App Store / Google Play store responses against a real disposable PostgreSQL schema and the production billing service code. No production/store publication and no Cloudflare/DNS changes are performed.

## App Store simulated lifecycle
Passed end-to-end through the authoritative server lifecycle:
- initial purchase verification
- renewal
- duplicate notification replay protection
- failed renewal + grace period
- restore/reconciliation
- plan upgrade
- plan downgrade
- refund/revocation and entitlement removal

## Google Play simulated lifecycle
Passed end-to-end through the authoritative server lifecycle:
- initial purchase verification
- server acknowledgement
- renewal + RTDN processing
- duplicate RTDN replay protection
- cancellation with paid access preserved until expiry
- grace period
- account hold and entitlement removal
- restore/reconciliation
- plan upgrade
- expiry and entitlement removal

## Acceptance environment
- Disposable PostgreSQL database migrated through Alembic head `20260809_0012`.
- Disposable Redis instance.
- Store network calls replaced only at the external-provider boundary with deterministic fake provider responses.
- All database writes, purchase persistence, subscription arbitration, event replay handling, and entitlement mutations use the real AIOS production service implementation.

## Boundary
A real Apple Sandbox / Google Play license-tester transaction still requires external store accounts, products and credentials. That is an external publication/onboarding validation step and is **not represented as having occurred** by this simulated acceptance.
