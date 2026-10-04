# FR-24A — Deterministic full-server-loss recovery-plan contract

Status: **source-level acceptance only; live recovery is NOT accepted or authorized**.

This bounded FR-24A package validates sanitized recovery metadata only. It does not read recovery keys, contact backup storage, mount filesystems, restore PostgreSQL, mutate production data, restart services, delete or rotate backup generations, or perform a live recovery drill.

## Contract covered

- Backup schema version 2 is required.
- Database, platform-asset snapshot and manifest roles require AES-256-GCM envelope version 1 metadata.
- The database and asset object keys must bind to the same canonical backup UUID and expected encrypted filenames.
- Ciphertext metadata must include a non-secret key identifier, ciphertext SHA-256 and ciphertext size larger than plaintext to account for authenticated-envelope overhead.
- The schema-2 manifest plaintext digest and size are recomputed deterministically from backup metadata and must match its protected manifest record.
- All 11 durable asset-root identifiers are mandatory and their per-root file/byte totals must equal the snapshot totals.
- Release evidence is bound to a clean source commit, compose digests, container image IDs/count and Alembic heads.
- Rollback evidence must remain preserved, non-overwritable and identical to the selected release source/compose/runtime evidence.
- Redis is explicitly excluded as cross-environment recovery authority and must use an empty rebuild/reconciliation strategy.
- Synthetic RPO is measured as loss detection minus backup cutoff; synthetic RTO is measured as service restored minus recovery start. Timestamps must be timezone-aware, monotonic and resolve to non-negative whole seconds.
- Live-recovery readiness is fail-closed on FR-05, FR-06, FR-22, coordinator approval and key-custody approval.

## Synthetic fixture

tests/fixtures/fr24/recovery_manifest.json contains only deterministic synthetic identifiers, hashes and timings. It contains no raw recovery key, no secret mount path, no production database/data, and no live backup object.

Expected synthetic measurement:

- RPO: 600 seconds.
- RTO: 1800 seconds.
- Live-ready: false.
- Open gates in the fixture: FR-06, FR-22, coordinator approval and key-custody approval.

## Scope boundary

This receipt proves only the FR-24A deterministic recovery-plan/manifest contract and isolated tests. It does **not** claim independent restore execution, non-empty recovered application acceptance, a real RPO/RTO measurement, or final FR-24 closure.

A controlled recovery drill remains externally gated on genuine FR-06 and FR-22 acceptance plus FR-25 coordinator and key-custody approval. Shared backup/deployment/storage wiring is outside FR-24 ownership and must be requested from FR-25 instead of being edited here.
