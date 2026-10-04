# FR-08C — automatic fair conversation scheduling

Status: source acceptance prepared; protected CI required before merge.

This increment removes the old one-turn-per-poll serialization in conversation_worker.py.
The worker now keeps a bounded active pool of four independent turns and refills free
slots automatically from a bounded queue scan.

Selection preserves accepted priority tiers. Within a priority tier it chooses the
least-represented user first, with oldest work as the stable tie-breaker. That gives
distinct users a fair first slot while still allowing one user to run multiple
independent conversations when capacity remains. A single conversation is selected
at most once per dispatch batch, and an already-active job ID is never selected again.

The existing durable run_turn no-replay boundary is unchanged: provider I/O starts
only after the queued row is durably committed as running; cancelled or uncertain
provider work remains non-replayable and requires reconciliation. Worker drain waits
for active work before cancellation and never turns a retained running row back into
queued work.

Targeted acceptance covers fair first slots across users, concurrent conversations for
the same user, priority preservation, one-conversation-per-batch, exclusion of active
job IDs, and automatic concurrent dispatch from the worker loop itself.

This is source-level FR-08C evidence. FR-08D still needs measured multi-user
queue/wait/resume evidence, and FR-08E still needs protected integration/merge and the
remaining end-to-end acceptance before FR-08 may be closed.
