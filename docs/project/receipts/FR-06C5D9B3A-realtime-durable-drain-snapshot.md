# FR-06C5D9B3A — Durable Realtime drain snapshot

Base: accepted main `23f44a95531099fd95cf3445009750c23d6069eb` after PR #756.
This increment is source-only measurement. It does not deploy migration 0064, contact LiveKit/Coturn, settle resources, or claim provider/full-host drain.

## Implemented boundary

The collector runs in one PostgreSQL REPEATABLE READ transaction and requires the current `realtime_media_requests` maintenance authority to be explicitly closed. Provider ownership rows must be strictly pre-closure: neither their admitted generation nor operation may belong to the current closed authority. Malformed ledger rows fail closed through the existing ownership validator.

The snapshot combines sanitized permanent provider ownership with durable room, participant, grant and recording state. It reports unfinished and unresolved provider rows, expired-but-unsettled participant-session ownership, active local rooms, connected/presence-bearing participants, active provider recordings, and legacy provider-bearing business rows that have no ownership history. It also retains legacy ambiguous recording starts as blockers.

The exported provider observation contains identifiers, kind/state, operation/generation and timestamps, but not the ownership nonce, provider-reference digest, raw unresolved reason, provider token, TURN credential, raw provider room identity or recording path.

An empty known-blocker set is only a local/durable observation. `coverage_unverified`, live provider inventory, connected-presence drain, TURN-allocation drain, provider drain and full-host closure all remain explicitly false until later provider-side acceptance.

## Safety boundary

No provider I/O, file mutation, admission transition, automatic settlement, retry or adoption is performed. Expired participant credentials are reported but not settled by the collector. Production remains on migration 0063; migration 0064 and the D9B2 ownership source remain unactivated until an independent rollout.
