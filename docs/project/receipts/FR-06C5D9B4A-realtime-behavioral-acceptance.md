# FR-06C5D9B4A — Behavioral Realtime drain safety acceptance

Reviewed base: PR #761 merge `9439a7f0520f38fb4c0ed6f966729f1bd3ccdc06`.
This follow-up completes missing behavioral coverage within D9B4; it is not a production activation or a new full-host-drain claim. The canonical current state remains `/opt/AIOS/docs/project/PROJECT-REPORT.md`, generated from the append-only runtime journal.

## Reproduced defects, not inferred test coverage

The first independent run on the unchanged PR761 source executed 45 tests against a disposable PostgreSQL instance: 23 passed and 22 failed, with zero setup errors/skips. Four failures demonstrated accepting a provider result after concurrent reopen, supersession, reopen/reclose, or a late local blocker. Eighteen malformed-entry cases showed that the inventory reader silently discarded invalid rows, coerced invalid identity types, or normalized identities instead of refusing the evidence.

A subsequent tenant-isolation case reproduced a third defect: ownership history for a different organization could mask an unowned local provider-bearing room because the historical lookup key lacked organization identity. This case failed before the key fix and passed afterward.

Retained before/after logs and JUnit evidence are under `docs/project/runtime/d9b4-resume-20260924/`: `baseline-red`, `fix-green`, `expanded-red`, and `expanded-green`. Runtime files are retained on the server rather than added as mutable Git evidence.

## Corrections

Inventory parsing now rejects malformed/empty/non-string/non-canonical/control-character identities and duplicate room/participant identities. Valid non-AIOS rooms remain outside the AIOS inventory scope. Missing or malformed list fields remain unavailable, not equivalent to an empty inventory. Exceptions use fixed messages without disclosing provider identities.

After the bounded provider read, a fresh PostgreSQL drain snapshot is mandatory. Its complete maintenance authority must match the initial snapshot; new blockers, changed ownership history, or a backward observation clock invalidate the result. Both snapshots are retained in the sanitized result. The provider read has a total 30-second deadline. Provider failures and cancellation propagate without settlement, retry, adoption, or database mutation.

Legacy ownership lookup is keyed by organization, resource kind, and local resource identity, preventing another tenant's history from suppressing a blocker.

## Actual isolated acceptance

The expanded suite contains 65 executable behavioral tests, all passed locally after correction. It uses real PostgreSQL transactions, row locks, authority transitions, and durable ledger calls. Coverage includes all four resource kinds in reserved/submitted/active/unresolved states; conservative session expiry and explicit settlement; legacy uncertain recording starts; cancellation after a committed Egress/file bundle; abrupt child-process exit after a committed provider intent; provider errors/deadline/cancellation; concurrent authority and blocker changes; malformed and duplicate provider data; tenant-scoped history; and valid hash-only observations with preserved counts.

LiveKit responses are explicitly simulated at the private transport boundary. No real provider call or credential is used. Abrupt process exit exercises a disposable child, not a production process or a full-host crash. Tables are created from the application's real metadata in per-test schemas; the existing dedicated ledger tests separately exercise migration 0064. The test runner uses a private internal Docker network, an ephemeral database, read-only source mounts, and cleanup of its specifically named containers/network.

## Remaining boundary

Passing this suite does not prove live LiveKit/Egress/Coturn drain, historical production reconciliation, absence of all filesystem writers, deployment coverage, or recoverability of the complete host. TURN allocation visibility, 0064 rollout, full-host closure and parent FR-06 completion remain unverified and unauthorized by these results. Current production version must be freshly checked in the independent rollout step; no production migration, deployment, service restart or provider mutation was performed here.
