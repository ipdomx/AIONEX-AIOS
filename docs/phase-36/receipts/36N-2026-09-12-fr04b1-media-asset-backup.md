# Phase 36N receipt — FR-04B1 media asset backup coverage

FR-04B1 extends the existing PostgreSQL + 3D platform-backup path with one additional production persistent root only: `media_asset_data`.

The implementation keeps the source volume read-only in the backup worker, creates a private manifest-backed tar companion, rejects unsafe paths/symlinks, records per-file SHA-256 and sizes, includes capacity/retention cleanup, replicates the companion to private R2 with full readback verification, and requires both local and off-site media snapshot validation during DR restore validation when enabled.

This receipt satisfies the Phase 36 reporting invariant for the changed backup/runtime paths. It is not a final FR-04 completion claim and does not cover the remaining persistent roots.
