# Phase 20 — Release Candidate

Phase 20 batches 1 through 4 establish the controlled release-candidate lifecycle:

- Release candidate identity, version, ownership, and state transitions
- Required validation gates for tests, security, migrations, rollback, and documentation
- Automatic blocking when any required gate fails
- Owner-scoped staged promotion through staging, canary, and production
- Release history and final production activation
- Unit tests for successful release, failed gates, and owner isolation

## Completion criteria

1. CodeQL passes.
2. Final Validation passes.
3. Every required release gate passes before approval.
4. Failed gates block the candidate.
5. Only the owning account can promote a candidate.
6. Production promotion marks the candidate released.

After this pull request is merged, Phase 20 is complete and the project can proceed to Phase 21: Stable Enterprise Release.
