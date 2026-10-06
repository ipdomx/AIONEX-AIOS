# FR-07F — Project conversation anti-stall and reconnect contract (2026-10-06)

Status: **candidate validated locally; protected CI required before merge**

Base source: PR #870 head `982bef753626a14b331eaabaeb0179223b093dca`.

## Problem closed by this batch

A durable conversation turn must never leave the user looking at an indefinite spinner with no trustworthy indication of whether work still exists. Browser disconnects, mobile app suspension, network timeouts, backend restarts, and uncertain provider outcomes must not cause a second charge or automatic provider replay.

## Contract

- The accepted user turn remains a durable `Job` keyed by the existing deterministic request identity.
- Browser conversation reads are bounded by a 12-second request timeout; enqueue/close writes are bounded by 20 seconds.
- If a send response is lost after server acceptance, the client retains the same request identity so a manual retry resolves to the same durable job and is not charged again.
- While provider I/O is in flight, the conversation worker persists a heartbeat every 10 seconds through `Job.updated_at`.
- A running conversation job with no heartbeat for 180 seconds is moved fail-closed to `needs_review`; it is **never automatically replayed**.
- Stale reconciliation records an audit event with `stale_heartbeat=true` and `automatic_retry=false`.
- Conversation history exposes `started_at`, `updated_at`, and `heartbeat_age_seconds`.
- The VIP UI polls durable history only; it never resubmits a turn during polling/reconnect.
- The selected conversation is preserved in the URL so a refresh/reopen can reconnect to the same durable conversation.
- The UI explicitly shows “still working” vs delayed/reconnecting state and the age of the last server heartbeat.
- Existing owner duration/message/credit policy remains authoritative and unchanged.

## Local validation

- Conversation governance + worker suite: **43 passed**.
- New heartbeat/stale-reconciliation integration cases run against a disposable PostgreSQL database: **PASS**.
- Worker fairness tests: **6 passed**.
- VIP locale integrity: **PASS — 6 complete locales, no simulated-data markers**.
- VIP TypeScript type-check: **PASS**.
- VIP static production build: **PASS**.
- Targeted VIP ESLint for the changed conversation files: **PASS**.
- Backend Ruff on changed services/tests: **PASS**.
- Mypy invocation in the reused local test image hit a mypy 2.3.1 internal error; this is not recorded as a source PASS and protected CI remains authoritative.
- Production was not modified by this candidate.

## Required protected acceptance

1. Merge PR #870 first after its exact-head protected checks are green.
2. Rebase/verify this batch on the resulting protected `main`.
3. Run protected backend, browser, VIP build, CodeQL, dependency/security, and production Docker gates.
4. Deploy only after protected CI is green, then smoke a real durable conversation without making duplicate provider requests.
5. Preserve rollback images and the old host until the existing NS-12 observation gate is complete.
