# 36H — Realtime provider inventory gate for FR-06C5D9B3B

This receipt binds the Phase 36-owned `web-dashboard/backend/app/realtime/livekit_runtime.py` change in PR #758.

The increment adds a read-only LiveKit provider inventory boundary for the FR-06 Realtime drain work. It exposes sanitized room and participant observations for later maintenance-drain comparison, without returning raw provider room names, participant identities, credentials, TURN usernames, TURN passwords, tokens, or provider secrets.

The provider inventory path is deliberately gated behind the durable D9B3A local snapshot: it is not allowed to run while durable/local Realtime blockers remain. It does not mutate rooms, participants, Egress, recordings, Coturn, PostgreSQL state, maintenance admission, or filesystem state.

This is source-only evidence. It does not deploy migration `20260920_0064`, does not execute provider inventory in Production, does not prove connected-presence drain, does not prove TURN allocation drain, and does not claim full-host closure.
