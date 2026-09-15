# FR-06C2D — database-vault Docker/host restart gate

Status: source-only until protected CI and separate production installation.

This part adds a second Docker `ExecStartPre` gate for the encrypted PostgreSQL domain. Docker may not start unless `aionex-database-vault` is active, mounted as the exact ext4 mapper with `nodev,nosuid,noexec`, and its `pgdata` subpath exists. It composes with the existing FR-06B asset-vault gate; neither gate unlocks key material.

The database cutover executor gains an explicit `guarded-start` path for daemon/host recovery. It accepts only a tamper-evident successful C2C cutover receipt, clean descendant `main`, exact database-vault host readiness, all PostgreSQL/database clients stopped, exact legacy/candidate PGDATA equality before start, and two explicit confirmations. If reboot removed the legacy read-only bind seal, the executor re-establishes it only after exact manifest equality. Candidate PostgreSQL must match the retained database identity/version/Alembic/table-count acceptance before the reconciler or clients start. The exact prior client scale is then restored with the already-reviewed `restart:no` overlays.

Any guarded-start failure after candidate PostgreSQL starts uses the existing offline automatic rollback path; it never copies PGDATA while PostgreSQL is running. Admission remains closed, Cloudflare is unchanged, and legacy PGDATA is never deleted by this part.
