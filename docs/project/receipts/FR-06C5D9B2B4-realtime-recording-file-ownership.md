# FR-06C5D9B2B4 — Durable Realtime recording-file ownership

Base: accepted main `4ceacd5316a07a73a6dda7210c17d507f97e69e0` after PR #755.
This increment is source ownership only. It does not deploy migration 0064, execute provider I/O in Production, certify provider drain, or close the host.

## Implemented boundary

A recording start now reserves both the LiveKit Egress owner and a separate `recording_file` owner for the same durable `RealtimeRecording.id` in the caller transaction. Both rows use the same owner incarnation and commit before `StartEgress`. A new bundle-begin operation locks both exact rows and consumes them atomically under one fresh check of the same open maintenance operation and generation. A close or generation change therefore cannot leave one capability newly consumed while the other remained reserved.

After LiveKit accepts the Egress start, the Egress identifier hash and a separate recording-file identity hash are persisted in their corresponding ownership rows before the business row publishes the provider Egress identifier. The file hash binds recording id, persisted output relative path and Egress identity without storing the raw path in the provider ledger. An ambiguous start/list/stop retains both started owners as unresolved and does not automatically retry, adopt or delete output.

Explicit Egress terminal observation can settle the Egress owner, but it does not settle the recording-file owner. The file owner remains a drain blocker while the existing recording finalizer validates/copies the MP4 into Studio and updates the recording business transaction. Only after that transaction commits does the route verify that the source path is absent and then settle the exact file owner. For `EGRESS_COMPLETE`, the committed recording must also expose its Studio asset, checksum and non-zero size. A remaining source path or an inability to prove absence retains unresolved ownership instead of deleting it. Failed/aborted terminal Egress may settle the file owner only when the source is explicitly absent.

The direct `finalize_completed_recording()` library function keeps its existing local behavior for compatibility and test callers; invoking it outside the ownership-bound API path is not host-drain evidence.

## Safety properties

- Migration `20260920_0064` remains source-only and is not applied to Production by this increment.
- Production remains on `20260920_0063`; no container, Cloudflare, provider or vault operation is performed here.
- Recording-file settlement requires exact owner identity, exact stored hash, terminal Egress status, business commit ordering and explicit source absence.
- A file still present after terminal state is retained as an unresolved blocker; no automatic cleanup is authorized.
- Egress completion alone is not recording-file drain proof, and recording-file source acceptance is not full provider or full-host drain proof.

## Acceptance target

Focused source contracts cover reservation/commit/bundle-start ordering, post-commit file settlement ordering, identity checks and plan truth. Isolated PostgreSQL tests cover atomic bundle consumption and narrow recording-file settlement. Full repository/backend/static checks must pass before protected PR merge. Production rollout of 0064 remains a later independent step.
