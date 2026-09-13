# FR-04C4 — DB/assets consistency and retention/delete contract

Scope: lock the current consistency boundary between PostgreSQL logical backups and the protected platform asset snapshot, plus deletion/retention semantics, as docs/tests only.

Contract:
- For `platform` backups, the database dump is created first and the platform asset snapshot is created as a companion archive derived from the database artifact path.
- A completed backup audit event must persist `three_d_snapshot` evidence: checksum, size, file count, payload bytes, and root totals when available.
- Restore validation must fail closed if a platform backup lacks durable snapshot evidence or the evidence is incomplete.
- Restore validation must validate the snapshot against durable checksum/size/count/payload evidence and expose `asset_snapshot_roots` when root totals are present.
- Retention/delete must treat DB dump and companion asset snapshot as one logical backup unit: expired artifacts delete the companion snapshot and database artifact, then keep checksum/size/timestamps/audit rows while clearing only the file location.
- Uncommitted/failed backups must cleanup both the companion snapshot and database artifact.

No runtime code change is introduced in this segment; it documents and tests the existing behavior before FR-04D non-empty backup acceptance.
