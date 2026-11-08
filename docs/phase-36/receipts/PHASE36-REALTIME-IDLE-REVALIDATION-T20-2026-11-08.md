# Phase 36 Reporting Receipt — realtime idle revalidation cadence (T-20)

- Receipt ID: PHASE36-REALTIME-IDLE-REVALIDATION-T20-2026-11-08
- Batch: pre-launch capacity fix (P6 gate 6.1, register item T-20). No capability maturity change.
- Date/time UTC: 2026-11-08
- Objective: Stop the per-socket idle revalidation from exhausting the API database pools at ~3000 connected users.
- Phase 36-owned paths touched: `web-dashboard/backend/app/realtime/authorized_socket.py` (new `ensure_token_current`, `FULL_REVALIDATION_EVERY_IDLE_TICKS = 6`) and `web-dashboard/backend/app/api/v1/endpoints/websocket.py` (idle cadence).
- Evidence: in the 6.1 production runs every connected socket ran a full database authorization every 5 s, about 600 per second at 3000 sockets and in synchronized waves. That produced `QueuePool limit ... reached` 500s while the host was idle and Postgres was fast.
- Security: idle ticks still verify signature, expiry and Redis revocation every 5 s, so logout and expiry still close an idle socket within one tick. The full database check (account, organization, plan, role, permissions, stream policy) runs every 6th idle tick from a random phase, and is unchanged before every delivered event. Committed revocation therefore still prevents the next delivery (FR-07D suite).
- Tests: `tests/test_t20_socket_token_revalidation.py` (no DB session on the cheap path; revoked or changed credentials close with 4403; bounded full-check cadence) and the existing FR-07D end-to-end revocation suite.
- Rollback: revert the PR. No data or schema change.
- External activation gates remaining: none.
