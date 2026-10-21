# AIOS continuity journal and CI backup-client alignment

Scope: AIONEX AIOS only. No application deployment or release-gate promotion.

## Observed failure

PR 953 head c6b27cb64a7cbc1ea8d7f916b2ef5f16e9bb4f2c passed the core,
frontend and production Docker jobs. Backend job 119378397832 in Final
Validation run 39645081696 failed the real PostgreSQL backup/restore smoke:
pg_restore attempted SET transaction_timeout against PostgreSQL 16.10,
which does not recognize that setting. The runner was Ubuntu 26.04 and
no matching host PostgreSQL client was selected by that job.

## Bounded repair

Pin only the host backend-test runner to Ubuntu 24.04, install its supported
postgresql-client-16 package and put its versioned binary directory first
in GITHUB_PATH. Before running migrations/tests, require pg_dump, pg_restore,
psql, createdb and dropdb to resolve to that directory and report major 16.
Leave the PostgreSQL service at major 16, RUN_LIVE_BACKUP_SMOKE enabled,
the strict restore behavior, tests and coverage threshold unchanged.
The production-container backup-worker version guard remains unchanged.

The accompanying continuity parser fix preserves valid Unicode characters
inside physical LF-delimited JSONL records and retains journal locks,
strict malformed-record handling, idempotent replay and release gates.
Existing and new parser tests passed 35/35 locally. The new CI contract
tests reproduce the missing client alignment before the workflow patch.
Remote CI on the amended exact head is required; this receipt is not a
claim of successful new remote CI, merge, deployment or full release.

## Evidence and remaining scope

NEW evidence: /var/lib/aionex-migration/launch-continuation-20261021T1730Z/.
No production container restart, customer/provider call, production load
test, OLD retirement or source-file deletion was performed. Expanded
OLD host-integration preservation gaps and the blocked transfer attempt
are tracked separately; neither this PR nor local tests close migration,
independent recovery, continuous stability or final launch acceptance.
