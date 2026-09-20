# FR-06D8C3 — Studio post-start cancellation receipt

Source-only increment over merged PR #733. It settles only a live cancellation
whose started execution has no unresolved/failed resources and whose publication,
if any, is complete with staging cleanup evidenced. Raw ledgers and any complete
archive are retained.

Migration: `20260919_0059`.

No production deployment, production migration, post-crash cleanup, automatic
retry, archive deletion or full-host closure is claimed. See the canonical project
receipt for acceptance evidence and limitations.
