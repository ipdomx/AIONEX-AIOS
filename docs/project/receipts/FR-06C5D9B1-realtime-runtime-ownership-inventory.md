# FR-06C5D9B1 — Realtime runtime ownership inventory

D9B1 is a source-only inventory after the accepted D9A Production rollout. It does not migrate or deploy Production and performs no LiveKit, TURN or Egress provider I/O.

The durable application model already retains five relevant families: `realtime_rooms`, `realtime_participants`, `realtime_admission_grants`, `realtime_recordings`, and `realtime_recording_consents`. The room retains a provider-room hash and fencing token; participant rows retain connection count, node, presence fencing and lease timestamps; admission grants retain expiry, consumption/revocation state and a provider-token JTI hash; recordings retain provider Egress ID, provider status metadata, output path/checksum/size/duration and terminal timestamps.

The activated provider runtime has independent external resources that are not yet maintenance-owned: LiveKit room existence, participant sessions and short-lived tokens, TURN REST credentials, Egress jobs, and recording files before durable Studio finalization. Room delete/participant removal/Egress stop are cleanup controls; their return or a local timeout alone is not proof that remote work ended.

The existing generic `host_maintenance_work_cycles` registry cannot be reused as-is: its database consumer constraint currently covers backup, academy, notification dispatch and security-remediation preparation only, and it has no Realtime resource-type discriminator.

The key remaining gap is explicit: none of the durable Realtime resource rows is bound to the current host-maintenance `operation_id` and admitted generation, and there is no durable ownership row covering provider-call start/return/ambiguity, no operation/generation-bound reconciliation of room/session/token/Egress/file lifetime, and no host-drain snapshot that proves all such resources terminal.

D9B2 must add durable provider-resource ownership before any attempt to claim Realtime drain. D9B3 must measure drain against one closed maintenance operation/generation across all historical and current resource rows, preserving unknown/ambiguous provider outcomes. D9B4 must prove cancellation/crash/timeout/provider-ambiguity behavior in isolated tests. `full_host_closure` remains false.
