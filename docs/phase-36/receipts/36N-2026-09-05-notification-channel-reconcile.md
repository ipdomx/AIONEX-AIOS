# Phase 36N — Notification channel reconciliation closeout — 2026-09-05

## Scope

Post-launch communications hardening for durable Owner alerts after channel configuration changes.

## Finding

Provider-credit predictive alerts were correctly deduped, but a pre-existing deduped Notification did not gain a newly selected delivery channel when Owner routing changed from Email fallback to Telegram. Existing Email deliveries that had already exhausted retries before the SMTP sender fix remained dead-lettered by design.

## Fix

- Preserve the existing Notification and dedupe key.
- Reconcile only missing selected delivery channels on a replay.
- Never duplicate an existing channel delivery.
- Keep existing failed/dead-letter deliveries unchanged until an explicit governed retry.
- Audit newly reconciled channels with `notification.delivery.channels_reconciled`.

## Verification

- Isolated PostgreSQL 16 + Redis 7 regression: `2 passed`.
- Replayed deduped notification gains one newly selected Email delivery and a third replay creates no duplicate.
- Existing Phase29E durable dedupe contract remains passing.
- Ruff PASS.
- Mypy PASS for `communications.py`.
- Repository security audit PASS.
- Python security audit PASS.

## Production follow-up after protected merge

The live provider-credit cycle must be run with the Owner Telegram channel ready. It must add Telegram deliveries to the three existing predictive-credit notifications. The three historical Email dead-letter deliveries must be explicitly requeued once after the SMTP sender fix. Acceptance requires Email and Telegram delivery receipts to reach `delivered` without changing provider funding amounts or exposing balances.
