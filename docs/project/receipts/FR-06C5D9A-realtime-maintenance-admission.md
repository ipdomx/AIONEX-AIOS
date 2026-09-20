# FR-06C5D9A — Realtime media maintenance admission

Source-only request/resume admission for Realtime media. Migration `20260920_0063` widens the existing host-maintenance authority from schema 7 to schema 8 by appending `realtime_media_requests`, while preserving open/closed state, operation id, reason, changed_at and `full_host_closure=false`; only the generation/version advances. No Realtime business row or provider state is backfilled or mutated by the migration.

New work is fenced at room creation, room join/token issuance, recording request creation, and positive recording consent. Provider recording start itself reacquires the same shared maintenance admission immediately before LiveKit Egress I/O, so a close after the consent commit cannot race into a provider start. GET-based refresh of a `starting` recording uses the same provider-start helper and is therefore fenced as a resume path.

Cleanup/control remains available while maintenance is closed: participant leave, room close and recording stop are intentionally not blocked. Read-only readiness/listing/provider-status refresh that does not create provider work is also not treated as new admission.

This stage does not add durable ownership for LiveKit rooms, participants, tokens, Egress jobs or recording files; it does not prove session drain, provider drain, token expiry, recording completion, Realtime full coverage, production deployment, or full-host closure. Those remain later boundaries.

Final local source acceptance before PR: 6/6 isolated PostgreSQL migration/locking cases passed; 7/7 D9A source-contract cases passed; combined D7 runtime-boundary + D9A contracts passed 25/25; the complete root repository suite passed 1969/1969. Ruff passed the modified Realtime/admission source and PostgreSQL test; Mypy reported no issues in the modified application sources. Phase 36 reporting, py_compile, PLAN JSON validation and git diff checks passed. The disposable PostgreSQL QA instance was idle before cleanup. No Production migration or deployment was performed by D9A source work.
