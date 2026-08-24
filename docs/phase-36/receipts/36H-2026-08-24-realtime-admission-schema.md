# Phase 36H Part 2A — Durable realtime admission schema receipt

Date: 2026-08-24

Status: **SOURCE AND ISOLATED MIGRATION VERIFIED — NOT MERGED OR DEPLOYED YET**

## Objective

Create the durable, tenant-scoped database authority required before realtime room admission can allocate an SFU, TURN relay, screen-share stream, or recording job. This sub-part deliberately contains schema, migration, constraints, tests, and evidence only.

## Completed

- Added `RealtimeTenantQuota`, `RealtimeRoom`, `RealtimeParticipant`, and `RealtimeAdmissionGrant` models.
- Added Alembic revision `20260824_0040`, linear from `20260823_0039`.
- Added bounded tenant quotas for rooms, participants, publishers, screen shares, recordings, admission rate, and grant TTL.
- Added idempotency keys and durable room fencing state.
- Persisted admission authority as SHA-256 digests only; no raw join credential, provider token, secret, or credential column exists.
- Added short-lived, single-use grant state with an expiry-after-issue database check.
- Added database-enforced composite tenant boundaries for room-to-workspace/project/creator, participant-to-room/user, and grant-to-room/participant/user/issuer relationships.
- Added reversible supporting unique constraints on `(id, organization_id)` for users, workspaces, and projects so PostgreSQL can enforce the composite foreign keys.
- Updated the shipped Alembic head expectation to `20260824_0040`.
- Added metadata, constraint, privacy, and migration-contract regression tests.

## Isolated PostgreSQL evidence

The final acceptance used a disposable `postgres:18-alpine` database. Production PostgreSQL was not addressed or modified.

- Migration sequence: `20260824_0040 -> 20260823_0039 -> 20260824_0040`.
- Realtime table presence: `4 -> 0 -> 4`.
- Supporting composite unique constraints: `3 -> 0 -> 3`.
- Ten actively executed invalid-link/check cases were rejected by PostgreSQL.
- Cross-tenant links accepted: `0`.
- Valid retained fixture rows: one quota, one room, one participant, one grant.
- Raw admission credentials persisted: false.
- Evidence: `.deployment-backups/phase36h-part2/20260824T113447Z/migration-and-tenant-constraints.json`.
- Evidence SHA-256: `8b2ae400e54b3322d012074f0ff49dcf97fb41a4edb575f59977fa4e939e6ed1`.

## Local validation

- Focused Backend regression set: `30 passed`, `0 failed`, with two existing dependency deprecation warnings.
- Root Phase 36 governance + zero-dead + market-readiness regression set: `18 passed`, `0 failed`.
- Realtime admission schema/head set: `6 passed`, `0 failed`.
- Ruff on changed Backend source/tests: PASS.
- Focused Mypy on models, migration, and schema tests: PASS.
- Alembic shipped head discovery: `20260824_0040 (head)`.
- `git diff --check`: PASS.
- No disposable migration container remains.

## Explicitly not completed in Part 2A

- No durable admission service or API route was implemented.
- No live quota counter, rate limiter, backpressure decision, presence lease, grant issuance, consumption, or revocation service was implemented.
- Migration `0040` was not applied to production.
- No production database backup/restore or deployment was performed in this source-only sub-part.
- No production service or container was restarted or recreated.
- No existing `/realtime/connect` route was rewired.
- No LiveKit/SFU, TURN/STUN, Egress, screen-share, recording, or media port was activated.
- No firewall, DNS, tunnel, secret, or provider configuration changed.
- No provider request, GPU job, or provider spend occurred.
- No 1000-user admission or media load claim was made.
- Phase 36G external song-runtime gate remains unchanged.

## Incident/change ledger

### 36H-P2A-001 — Local Alembic discovery initially lacked a test Settings secret

- Symptom: the first `alembic heads` invocation stopped during Settings construction because the generic shell environment had an empty `SECRET_KEY`.
- Root cause: the repository validation environment requires an explicit non-production test secret when migrations import application metadata.
- Fix: reran validation with synthetic test-only Settings values. No production secret was read, copied, or changed.
- Impact: validation-only; no database connection or migration occurred during the failed invocation.

### 36H-P2A-002 — Initial schema test compared names with SQLAlchemy Column objects

- Symptom: two new metadata assertions failed while all expected columns were present.
- Root cause: the test used `set(table.c)` instead of `set(table.c.keys())`.
- Fix: compare deterministic column-name sets and add focused typing to the constraint helper.
- Regression: schema/head tests pass `6/6`; focused Mypy passes.

### 36H-P2A-003 — First design did not enforce every user/workspace/project tenant match in PostgreSQL

- Symptom: review showed room/participant/grant service code could have been required to prevent some cross-tenant references without a database composite FK.
- Root cause: existing user/workspace/project primary keys are globally unique, but their ordinary single-column foreign keys do not prove that the referenced row belongs to the submitted `organization_id`.
- Fix: add reversible `(id, organization_id)` unique constraints and composite tenant foreign keys for every realtime relationship.
- Security result: ten invalid cross-tenant or bounds cases are now rejected by PostgreSQL; zero invalid links were accepted.

### 36H-P2A-004 — First constraint fixture was inserted in an unsafe dependency order

- Symptom: the first isolated constraint run attempted to flush users before their referenced workspaces and PostgreSQL rejected the insert.
- Root cause: ORM fixture objects had no declared relationships that guaranteed flush ordering.
- Fix: create organizations, workspaces, users, projects, rooms, participants, and grants in explicit committed dependency stages.
- Impact: disposable validation database only; its container was removed automatically.

### 36H-P2A-005 — Whole-file formatter expanded the model diff unnecessarily

- Symptom: formatting the consolidated model file produced a multi-thousand-line unrelated diff.
- Root cause: the file contains historical formatting that differs from the current formatter output.
- Fix: discard the broad formatting change, restore the tracked files, and reapply only the intended model/import/constraint block.
- Result: the final tracked model change is a focused addition rather than a repository-wide formatting rewrite; `git diff --check` passes.

## Rollback

Before deployment, rollback is a source revert. The migration downgrade removes the four realtime tables and the three supporting unique constraints, returning the isolated schema to revision `20260823_0039`. A future production application of `0040` requires its own backup, deployment, and restore evidence and is outside Part 2A.

## Next safe sub-part

After protected PR validation and merge, implement `36H.2B`: tenant-scoped room admission, transactional quota/backpressure decisions, short-lived hash-only grant issuance/consumption/revocation, presence leases, and deterministic concurrency tests. Keep SFU/TURN/recording disabled.
