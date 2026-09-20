# FR-06C5D9B2A — Durable Realtime provider-resource ledger

D9B2A adds source infrastructure only. The new permanent `realtime_provider_resources` registry is separate from `host_maintenance_work_cycles` because the generic cycle table neither permits the Realtime consumer nor distinguishes room/session/Egress/file resources.

A registry row binds tenant, resource kind, local resource UUID, caller incarnation, admitted authority generation and authority operation ID to an opaque ownership nonce. Supported kinds are room, participant session, Egress and recording file. Evidence is permanent; business-row deletion does not cascade into this table. A partial unique index permits at most one unfinished ownership attempt per local resource while retaining settled historical attempts. A later explicit attempt is possible only after prior evidence is settled; nothing in this ledger performs automatic retry.

Provider intent is reserved under the existing schema-8 `realtime_media_requests` shared admission lock inside the caller transaction. No provider capability is consumable until that transaction commits: `begin_provider_io` uses an independent transaction, reacquires open Realtime admission, requires the exact same operation/generation and changes a single reserved row to submitted before returning. A maintenance close or generation rollover therefore prevents a reserved request from starting provider I/O.

Submitted or active ownership cannot be erased as `not_started`. Provider timeouts/cancellation/errors are retained as unresolved evidence. Only a still-reserved capability can settle as not-started. Resource-specific active settlement (room deletion, token/TURN expiry, Egress terminal reconciliation and recording-file finalization) is intentionally deferred to later D9B2 parts.

The migration is `20260920_0064`; it creates only the permanent registry and fails closed on incompatible pre-existing schema. Downgrade refuses to discard evidence. D9B2A does not wire API routes, migrate Production, contact LiveKit/TURN/Egress, prove session/provider drain or claim full-host closure.
