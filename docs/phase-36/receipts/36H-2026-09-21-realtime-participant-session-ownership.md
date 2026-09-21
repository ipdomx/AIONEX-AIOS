# Phase 36H — Realtime participant-session ownership source receipt

Date: 2026-09-21
Scope: source-only FR-06C5D9B2B2 hardening of the already-activated Phase 36H Realtime runtime.

This receipt records a source change to the LiveKit/Coturn participant credential path. It does not change the Phase 36H maturity claim, does not deploy migration `20260920_0064` to Production, and does not certify Realtime session drain or full-host closure.

The join path now commits the durable admission grant and a `participant_session` provider-ownership intent before minting any LiveKit JWT or TURN REST credential. The durable local identity is the grant UUID so separate issued bundles for one participant remain independent evidence. Capability start reacquires the schema-8 Realtime maintenance authority and requires the exact original maintenance operation and generation.

A successful credential bundle persists an opaque ownership reference covering both the LiveKit token JTI and TURN credential identity. Its drain deadline is the later of JWT expiry and TURN credential expiry, and that evidence is durable before the grant is consumed or the credentials are returned. Mint/consume ambiguity is retained rather than retried or adopted automatically.

`leave_room` deliberately does not settle the credential ownership. Removing a participant from LiveKit does not revoke an already-issued JWT or TURN credential, and credential expiry itself does not prove an already-connected participant or TURN allocation has ended. Database-clock expiry can settle only the credential-capability evidence; connected-presence/provider drain remains open FR-06 work.

Local acceptance for the source candidate before PR update: focused FR-06 contracts 49/49, root suite 1996/1996, isolated PostgreSQL provider tests 9/9, Realtime backend suite 75/75 after Alembic `0064`, Ruff PASS and Mypy PASS. No acceptance-time LiveKit/TURN provider mutation or Production change was performed.

Detailed FR evidence: `docs/project/receipts/FR-06C5D9B2B2-realtime-participant-session-ownership.md`.
