# FR-06D8C4B3 — Studio cleanup candidate

Dependent source increment after C4B2. It exports a private, database-only cleanup candidate from a retained C4A crash observation, execution ledger, and publication journal under the same current closed maintenance operation/generation.

Only bounded layouts are exportable: no archive entry, owned staging only, owned final only, or owned staging/final hardlinks. The exporter verifies execution/publication digests, exact configured Studio root, tenant-relative path components, and absence of conflicting terminal receipts. It exports relative components and identities only; it performs no filesystem read/write/delete, no business mutation, and no settlement.

The candidate keeps `final_deletion_permitted=false`, `cleanup_authorized=false`, `filesystem_mutation_performed=false`, and `full_host_closure=false`. A later host-side stage must still prove exact process references are drained before any staging unlink.

Local draft acceptance: 13 focused PostgreSQL/filesystem/source cases, Ruff success, mypy success across 289 application files, and 1838/1838 root repository tests. The branch remains dependent and is not opened for merge until C4B2 is accepted.
