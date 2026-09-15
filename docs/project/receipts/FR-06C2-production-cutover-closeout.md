# FR-06C2D — production database-vault cutover closeout

FR-06C2 is accepted for its database domain. The restart-gate source in PR #688 merged as `6a153a5a5c307dfe6d76a0f5a9a9e510a64a2aed`, and all 11 exact post-merge main checks passed, including Production Docker Build and backup/restore smoke. The live PostgreSQL cluster was cut over only after the protected C2C executor merged and exact-main checks passed. The executor drained database clients, stopped PostgreSQL cleanly, sealed legacy PGDATA read-only, copied PGDATA offline including `pg_wal`, matched exact manifests, started PostgreSQL on the mapper-backed encrypted `database-vault`, validated database identity/schema/counts before restarting clients, and retained admission closed.

The candidate database is now authoritative on `aionex-fr06-database-vault`. Legacy `web-dashboard_postgres_data` remains mounted read-only and is not deleted. A fresh platform backup created after the database cutover completed locally and to encrypted R2, and its independent restore validation completed with both local and off-site validation true.

The database Docker fail-closed drop-in is now installed alongside the FR-06B asset-vault gate. `systemctl daemon-reload` completed and the installed file matches the repository SHA-256. A second Docker restart is intentionally not performed here: FR-06C6 owns the real all-domain host reboot/recovery acceptance. The installed gate already ensures a future Docker start is refused if the database mapper/mount/subpath is absent.

FR-06C2 is therefore complete, but FR-06 remains open. Next is FR-06C3 for the local-backup vault and Redis/operations domain with independent rollback and recovery evidence.
