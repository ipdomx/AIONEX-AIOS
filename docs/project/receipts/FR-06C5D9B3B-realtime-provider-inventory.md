# FR-06C5D9B3B — LiveKit provider inventory drain gate

Base: accepted main `e0da94082d333c1a68f6fcad9a04cda053e839fa` after PR #757.
This increment is source-only. It adds the provider inventory path needed after a clear D9B3A durable snapshot, but it does not run provider I/O in Production, deploy migration 0064, settle resources, or claim full Realtime drain.

## Implemented boundary

The LiveKit runtime can now perform read-only `ListRooms` and `ListParticipants` calls on the private control plane. Returned evidence is sanitized: AIOS room names and participant identities are represented only as SHA-256 hashes/counts. Raw provider room names, participant identities, tokens, TURN credentials and provider secrets are not returned or persisted.

The provider inventory service first collects the D9B3A durable drain snapshot. It refuses to call LiveKit unless the known durable/local blocker set is empty. This prevents provider inventory from hiding unresolved ledger rows, legacy unowned resources, connected local participants or active recordings.

The service does not commit, roll back, mutate providers, delete files, close admission, retry work, adopt orphan work or settle ownership. LiveKit empty-room inventory may support connected-presence drain after execution in a later rollout, but TURN allocation drain remains explicitly unverified because the current Coturn contract does not expose a safe allocation inventory API.

## Safety boundary

Production remains on schema `20260920_0063`; migration `20260920_0064` is still source-only. This part is not a full provider drain receipt and not a full-host closure receipt.
