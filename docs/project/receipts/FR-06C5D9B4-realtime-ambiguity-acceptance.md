# FR-06C5D9B4 — Realtime ambiguity acceptance

Base: accepted main `9df4d7e845b870fcf4ce6aa2668b6f9fbe00f7f4` after PR #760.

This is a source-only acceptance boundary for crash, cancellation and provider ambiguity states in the Realtime/LiveKit maintenance path. It consumes the durable D9B3A drain snapshot and refuses acceptance while any submitted, active or unresolved provider ownership remains, while expired participant-session ownership is not settled, or while legacy ambiguous recording starts remain.

No provider I/O, cleanup, database mutation, settlement, retry, adoption, admission transition, Production migration, 0064 rollout authorization, provider-drain claim or full-host-closure claim is performed.
