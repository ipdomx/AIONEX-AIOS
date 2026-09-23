# FR-06C5D9B3C — Bounded Realtime provider drain boundary

Base: accepted main `8447d53578b70c56faede737a80ffa8c950504e1` after PR #758.
This is source-only. It does not deploy migration 0064, run provider inventory in Production, settle provider resources, or claim full provider/host drain.

## Boundary

D9B3C binds the D9B3A durable/local drain snapshot to the D9B3B provider-inventory source. Provider inventory is still gated behind a clear durable snapshot. LiveKit room and participant observations are returned as SHA-256 identities and counts only.

The result separates the claims:

- Connected-presence provider drain is bounded only by no LiveKit participants inside AIOS-owned rooms.
- LiveKit room drain is bounded only by no AIOS-owned LiveKit rooms.
- TURN/Coturn allocation drain remains unverified because the current deployment contract has no safe allocation inventory API.
- Therefore provider_drain_verified and full_host_closure remain false.

No cleanup, retry, adoption, settlement, provider mutation, database write, Production migration or Production execution is authorized by this increment.
