# NS-15 continuity, exact-SHA and client-delivery policy — 2026-10-06

Status: **reviewed documentation candidate; no production mutation**

This receipt records three controls requested during final-release continuation:

1. **Client delivery/stream resilience is now explicit release scope.** The observed external ChatGPT “streaming interrupted” UI is not treated as proof of an AIOS defect. Instead, the analogous AIOS failure class is made a required acceptance item: durable job identity, bounded timeout/heartbeat, reconnect/resume or durable-status fallback, idempotent de-duplication, no duplicate provider charge/execution, and explicit reconnect/recovery/failure UI states.
2. **New-server operation is exact-SHA bound.** MCP2 may enter through the retained management host and then use the approved administrative channel to the new server. GitHub exact SHA is resolved before mutation; a clean SHA-bound worktree/checkout is used; exact-head CI is not reused for a different commit; rollback images/source are preserved; live runtime identity and health are reverified after rollout. No credentials, private key material or raw host secrets are documented.
3. **Every material state transition is retained.** PASS, FAIL, BLOCKED/HOLD, PENDING_RETRY, ROLLBACK, IN_PROGRESS and COMPLETE are preserved in the runtime journal/checkpoint with SHA/evidence/next-action fields. The canonical map is the reviewed summary and is reconciled at material checkpoints rather than on every transient CI poll. Generated STATE.json and PROJECT-REPORT.md remain project_hub outputs only.

This documentation change does not claim that client streaming resilience is already implemented or accepted. Its status remains **REQUIRED_PENDING_IMPLEMENTATION_AND_ACCEPTANCE** until source, protected CI and runtime acceptance evidence close it.
