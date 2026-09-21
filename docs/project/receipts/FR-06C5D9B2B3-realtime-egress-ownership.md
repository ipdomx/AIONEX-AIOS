# FR-06C5D9B2B3 — Durable LiveKit Egress ownership

D9B2B3 wires only LiveKit Egress start/list/stop to the permanent provider ledger. It does not own recording-file finalization and does not deploy migration 0064 to Production.

A `starting` recording and reserved `egress` ownership row commit before `StartRoomCompositeEgress`. Capability start reacquires the same schema-8 maintenance operation/generation. A maintenance close or generation rollover can therefore settle only never-started reserved intent; authority uncertainty preserves the intent for reconciliation.

Start response ambiguity no longer marks the recording failed and never triggers automatic Start retry. The ownership remains unresolved, so later reads cannot invoke another provider start until explicit reconciliation. Successful Start persists the SHA-256 of the returned Egress ID as active provider ownership before the business recording advertises that provider identifier.

List and Stop observations are checked against the durable Egress identity. Provider errors retain unfinished ownership. `StopEgress` acknowledgement is not terminal evidence: `EGRESS_ENDING` remains unfinished. Ownership settles only from explicit `EGRESS_COMPLETE`, `EGRESS_FAILED` or `EGRESS_ABORTED` observations.

A provider-terminal Egress can settle independently of local MP4/Studio finalization; recording-file ownership is intentionally deferred to the next D9B2 part, so provider drain and full-host closure remain false. Legacy recordings without D9B2 ownership retain compatibility but are not retroactively adopted.
