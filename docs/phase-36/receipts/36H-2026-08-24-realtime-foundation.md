# Phase 36H Part 1 — Realtime foundation receipt

Date: 2026-08-24

Status: **IN PROGRESS — source foundation only**

## Completed in this part

- Revalidated the actual starting state: both existing AIOS WebSocket managers are process-local and cannot satisfy the final horizontal-scale contract.
- Recorded the latest-stable technology review and the provider-neutral target architecture in `docs/phase-36/PHASE_36H_REALTIME_FOUNDATION.md`.
- Selected LiveKit as the first SFU/signaling adapter candidate without binding AIOS durable policy to LiveKit-specific identifiers.
- Kept the exact LiveKit production version unresolved pending bounded high-room-churn soak evidence; latest observed `v1.13.5` is not automatically approved.
- Added a dormant Redis realtime backplane contract with SHA-256 tenant channel derivation, bounded JSON-object events and dynamic per-tenant subscriptions.
- Added a dormant distributed local fanout hub that subscribes on first local client and unsubscribes on last local client.
- Added deterministic multi-node tests proving same-tenant fanout and no cross-tenant delivery.
- Updated the authoritative Phase 36 roadmap and external project reports.

## Explicitly not completed in Part 1

- No production `/realtime/connect` route was rewired.
- No SFU server was deployed or activated.
- No LiveKit version was pinned for production.
- No TURN/STUN service was deployed or activated.
- No firewall or DNS change was made.
- No room/session database migration was created.
- No short-lived media join-token service was activated.
- No recording/Egress service was deployed.
- No Creative Studio recording ingestion was activated.
- No 1000-user realtime load test was claimed.
- No production service was restarted.
- No paid provider request, GPU job or provider spend occurred.
- Phase 36G song production was not relabeled `runtime_verified`; its external live gate remains carried forward.

## Focused evidence

- `tests/test_phase36h_realtime_foundation.py`: 5 passed.
- Combined Phase 36 capability + Part 1 focused tests: 6 passed, 2 dependency deprecation warnings.
- Ruff on new realtime source/tests: PASS.
- Mypy on new realtime source/tests: PASS.
- Python compileall on new realtime source/tests: PASS.

## Rollback

Source-only revert. There is no migration, production activation, provider job, network rule, secret change or service restart to roll back.

## Validation note

A broad Mypy invocation initially reported 33 errors across 17 files. Exactly one was on the new Part 1 registry change (`external_gate` missing from `BatchStatus`) and was fixed. The other 32 findings are in unchanged modules outside this Part 1 changed surface and are **not** claimed fixed. Focused Mypy on the Part 1 registry and realtime source now passes.

## Protected CI correction

The first PR #491 run found two Part 1 regressions: the root zero-dead audit rejected a bare `pass` in cancellation handling, and the VIP browser test still asserted visible batch `36G` after its mock moved to `36H`. Both were fixed before merge. Regression set: zero-dead + market-readiness + Phase 36 governance `18/18` PASS; backend capability + Part 1 `6/6` PASS; Ruff/Mypy PASS. No production deployment occurred during the failed run.
