# FR-06C5D9B2B2 — Durable participant-session credential ownership

D9B2B2 wires only participant join-session capabilities to the permanent D9B2A provider ledger. It does not wire Egress or recording-file ownership and does not deploy migration 0064 to Production.

The durable local identity for one participant-session attempt is the admission-grant UUID, not the participant UUID. This allows multiple historical or overlapping session credentials for one participant to remain independent drain evidence. Grant creation and a reserved `participant_session` ownership row commit together before any LiveKit JWT or TURN REST credential is minted.

After commit, the room and participant are re-locked and `begin_provider_io` reacquires schema-8 Realtime admission and requires the exact original maintenance operation/generation. A maintenance close or generation rollover therefore revokes the still-issued grant and settles only the never-consumed reserved intent; authority unavailability preserves evidence for reconciliation.

A successful participant bundle records an opaque ownership hash covering both the LiveKit token JTI and TURN credential identity, while the existing grant continues to store only the token-JTI SHA-256. The ledger expiry is the later of JWT expiry and TURN REST credential expiry. The capability bundle becomes active durable evidence before the grant is consumed or returned to the caller.

`leave_room` intentionally does not settle participant-session ownership: removing a participant from LiveKit does not revoke an already-issued JWT/TURN credential. Expiry settlement requires the PostgreSQL clock to observe the whole-bundle deadline. That settlement proves only that the issued JWT/TURN capability bundle expired; it does not prove an already-connected LiveKit participant or TURN allocation has ended. A mint failure after capability start is retained as unresolved with a conservative maximum credential deadline; submitted/active evidence is never rewritten as `not_started`.

This source stage performs no Production migration, no acceptance-time LiveKit/TURN provider I/O, no Egress/file ownership, no session-drain proof and no full-host closure.
