# FR-06C5D9B4A2 — Settlement evidence integrity

Reviewed base: PR762 merge `985fa4aa6c05c56356a92f6d848ed46e20c1197e`.
This is a targeted correction inside D9B4, separate from the parallel Coturn observer integration. It does not advance the parent source part, migrate 0064, settle any production row, or authorize rollout.

## Reproduced failure

A PostgreSQL-backed regression run on the unchanged base accepted 14 malformed settled ledger records. Twelve cases covered each of the four resource kinds with settlement preceding the intent, preceding provider start, or following the last recorded update. Two participant-session cases lacked expiry evidence or retained credentials whose expiry was after settlement. These rows satisfy the existing table constraints, but the application validator previously accepted them and the collector could report a locally clear snapshot.

The test fixture deliberately introduces inconsistent rows only into isolated per-test PostgreSQL schemas. This is fault injection, not evidence that production contains corrupt records or that the ordinary settlement APIs emitted them.

## Correction

The shared ownership validator now rejects a settlement outside the intent/update chronology or before provider start. A started participant-session owner cannot be accepted as settled without a bundle expiry no later than settlement. A reserved intent that never began provider I/O can still be settled without a credential expiry.

This validation runs on ledger reads and existing mutation preconditions. It performs no repair, retry, adoption, expiry settlement, provider request or cleanup. Invalid evidence must be reconciled separately; it must not erase a drain blocker.

## Executed acceptance

Retained under `/opt/AIOS/docs/project/runtime/d9b4a2-settlement-evidence-20260924/`:
- `baseline/`: 14 reproduced failures, 4 passing valid no-start controls, no setup errors/skips.
- `fixed/`: all 18 new regressions passed after the validator correction.
- `full/`: 96 combined PostgreSQL behavioral and provider-ownership tests passed, no failures/errors/skips.

Each run used a fresh private internal Docker network, disposable PostgreSQL on tmpfs, read-only source and container root, dropped runner capabilities, and synthetic test credentials. Specifically named test containers and networks were removed. LiveKit/Coturn/production database were not contacted. Root/static quality and protected CI are reported separately by their actual results in the canonical journal.

## Main advancement and cross-integration verification

The original PR765 head `202077eaaefbf200197c1bb6b13d87bb35caf159` passed all 12 reported checks. A normal merge request was then refused because main had advanced to `95e70d0a880242fe62e3094446092c3a5bc7b570` and the two branches appended different entries to PLAN.json. No protected-main change was made by that refused request.

The updated main was merged into this feature branch without a force push. Resolution retained the entire new main plan and the exact additive settlement-validation record; the source correction and all observer work were preserved. On this reconciled source, all 2,197 root tests and 96 PostgreSQL behavioral/ownership tests passed. An earlier independent check of the immutable observer integration `1decd4a4` also passed its 171 executable observer/authority tests. This is cross-integration evidence, not a claim of runtime deployment or an exemption from renewed protected CI on the new head.
