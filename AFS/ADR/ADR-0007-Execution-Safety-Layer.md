# ADR-0007: Execution Safety Layer

## Status
Accepted for AIOS v1.1.0-alpha.4.

## Decision
Every state-changing operation must be represented as an immutable execution plan and pass through a dry-run-first safety layer. Apply mode requires policy validation, reproducible experiment evidence, appropriate approval, and a rollback plan for high-risk work.

## Required controls
- Dry run is the default mode.
- Destructive and network operations are denied unless explicitly allowed.
- Filesystem access is constrained to approved roots.
- High-risk actions require rollback instructions.
- Existing targets are snapshotted before mutation.
- Every planned, blocked, failed, or successful execution is persisted.
- Production policy is stricter than development policy.

## Consequences
AIOS gains controlled execution and auditable evidence. This layer does not claim that arbitrary commands are safe; future SSH, container and cloud adapters must use this contract rather than bypass it.
