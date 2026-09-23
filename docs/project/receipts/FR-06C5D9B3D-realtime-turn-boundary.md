# FR-06C5D9B3D — Realtime TURN/Coturn drain boundary

Base: accepted main `9a960bcac73e3123ea9433ec4fe01b3239fe15c7` after PR #759.
This source increment does not deploy migration 0064, run Production provider inventory, settle resources, clean up provider state or claim full provider drain.

D9B3D consumes the D9B3C LiveKit provider inventory result and records the remaining provider truth boundary. LiveKit room and participant inventory can bound AIOS room presence and connected participant presence through hash-only observations. Coturn allocation drain remains unverified because the current Coturn deployment contract exposes no safe allocation inventory API.

Therefore `turn_allocation_drain_verified`, `provider_drain_verified`, `full_host_closure` and `migration_0064_rollout_allowed` remain false. Any 0064 rollout must remain a later independent window with fresh authority, backup/restore and live acceptance.
