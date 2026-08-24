# Phase 36H — Part 2B Realtime Admission Service Receipt

Date: 2026-08-24
Status: source implemented; isolated PostgreSQL runtime verified; production unchanged.

## Implemented

- Provider-neutral `RealtimeAdmissionAuthority` shared by API nodes through PostgreSQL transactions.
- Tenant quota row lock as the serialization boundary for room creation and admissions.
- Idempotent room creation with tenant room and room-capacity backpressure.
- Per-tenant/per-room participant, publisher, screen-share and rolling-window admission limits.
- Short-lived, single-use admission grants; raw bearer values are not persisted.
- Deterministic HMAC bearer reconstruction for safe idempotent replay while the grant remains active; database stores SHA-256 only.
- Tenant-scoped grant consume/revoke lifecycle with row locks, expiry, revocation and single-use enforcement.
- Alembic `20260824_0041`: participant presence fencing token + lease expiry, check constraint and indexes.
- Presence claim/renew/heartbeat/release/stale-reap with node ownership and fencing.
- Atomic room fencing advancement for future provider ownership.

## Verification

- Isolated PostgreSQL 18 migration: `0041 -> 0040 -> 0041` PASS.
- Presence fields after downgrade: absent; after upgrade: both present.
- Presence fencing check and indexes restored after upgrade.
- Focused Backend/36H tests: `15 passed`.
- Root Phase 36 governance + zero-dead + market-readiness: `18 passed`.
- Ruff: PASS.
- Focused Mypy: PASS.
- Concurrent two-session capacity-one admission: exactly one accepted; one rejected by participant backpressure.
- Grant single-use, rate-limit, room/publisher/participant backpressure, idempotent replay, takeover, heartbeat and stale-fence behavior covered.

## Problems observed

- First schema-only test invocation from repository root loaded a legacy root `.env` Telegram list that Pydantic could not parse. The test was rerun from the Backend directory with an explicit synthetic test environment; no production secret was used.
- First disposable PostgreSQL start attempted host port `55441`, already occupied by an unrelated listener. Docker rejected the bind before the test container started. The isolated test used `127.0.0.1:55491` instead; production networking was not changed.

## Explicitly not completed

- Production DB remains `20260823_0039`; migrations `0040/0041` are not applied.
- Existing `/realtime/connect` is not rewired to this authority yet.
- No SFU/LiveKit, TURN/STUN, Egress/recording, screen-share media path or provider token issuance.
- No production service/container restart or recreation.
- No firewall, DNS, tunnel, credential or provider configuration change.
- Provider requests: 0. GPU jobs: 0. Provider spend: $0.00.
- No 1000-user realtime load, media failover or recovery certification claim.
- A closing Ruff command initially used repository-relative paths while its working directory was already `web-dashboard/backend`, producing only path-not-found errors. It was rerun with Backend-relative paths and passed; no source/runtime failure occurred.
- First protected PR #493 Backend run exposed one stale regression assertion: `test_backend_exposes_the_shipped_alembic_head` still expected `0040`. The migration itself had already succeeded in CI; the assertion was corrected to `0041` and added to the local closing gate before rerunning protected CI.
- The first command that attempted to append that CI incident used Backend cwd with repository-root report paths; those report writes failed and were immediately rerun from `/opt/AIOS`. The targeted Alembic-head regression test in that invocation passed; production was unaffected.
- A subsequent grouped closing command still invoked the repository-root reporting checker from Backend cwd and stopped before pytest. The commands were then permanently separated by cwd: reporting/diff from `/opt/AIOS`, Backend test from `web-dashboard/backend`; both passed.
