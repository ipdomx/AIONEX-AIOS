# FR-04C5 — FR-04C parent closure

Scope: close FR-04C as a documentation/test-only parent after the small FR-04C slices are complete.

Closed slices:
- FR-04C1: hard-linked source files are rejected before asset snapshot creation.
- FR-04C2: cache/socket/model volumes are explicitly excluded from asset snapshots; `backup_data` is destination-only.
- FR-04C3: `redis_data` is operational AOF/noeviction state and must start empty or be flushed for restored environments; it is not restored as an asset snapshot.
- FR-04C4: PostgreSQL logical backup and protected platform asset snapshot share one backup-set consistency boundary; retention/delete semantics are documented before FR-04D.

Acceptance:
- All C1-C4 receipts exist.
- Tests enforce that FR-04D is not considered started by this closure.
- No runtime code, Compose service, image, or backup-worker behavior changes in this parent closure.

Next: FR-04D can start only after this parent closure PR is merged and recorded.
