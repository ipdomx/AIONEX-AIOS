# FR-06C5D9B2B1 — Durable LiveKit room ownership

D9B2B1 wires only the LiveKit room lifecycle to the permanent D9B2A provider registry. It does not wire participant sessions, TURN credentials, Egress, recording files or claim Realtime drain.

Room creation now commits the planned business room and a reserved provider-ownership attempt together under schema-8 admission before external I/O. The reserved ownership cannot start LiveKit until `begin_provider_io` commits a second transaction that reacquires open admission and requires the exact admitted operation/generation. A maintenance close or generation rollover therefore freezes the planned room without provider mutation.

Before capability consumption the planned room row is re-locked and that row lock is retained across `CreateRoom`, preventing close-room from racing an in-flight provider create. Once the capability is consumed, the ownership row is submitted. Close-room never treats submitted state or an early provider not-found as settlement proof. `CreateRoom` success is persisted as active room ownership before the business room is marked open. If provider response is unavailable/protocol-ambiguous, ownership becomes unresolved and no automatic `DeleteRoom` is attempted. If the later local room commit fails, active ownership remains durable and blocks future drain claims.

Room close reads unfinished ownership. A still-reserved attempt that never consumed provider capability may settle as not-started. Submitted/active/unresolved room ownership settles only after LiveKit `DeleteRoom` succeeds or returns explicit not-found. Other provider errors retain unresolved ownership. Legacy rooms without D9B2 ownership remain closable but are not retroactively adopted.

This source stage does not execute migration 0064 on Production, contact LiveKit during acceptance, prove participant/token/Egress/file settlement, or claim full-host closure.
