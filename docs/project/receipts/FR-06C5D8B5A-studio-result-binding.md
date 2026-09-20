# FR-06C5D8B5A — Bind business acceptance to the owned Studio publication

Base: PR #729, merged as `abf1197c1b2106baab047e980c2df3c303a3ee31`.
The merge and exact-main acceptance are separate events in the canonical Project
Hub. This increment changes source only and introduces no database migration.

## Implemented boundary

The live worker validates output ownership before creating or updating an asset,
revision, terminal result, success notification or completion audit. It locks the
business job, exact execution and publication in the existing transaction and
retains those locks until that transaction commits or rolls back. The validator
suppresses pending autoflush and performs no commit, rollback, file operation,
thread submission, admission reopening, replay or resource release.

Acceptance requires an executing provider-neutral job and its exact nonce,
worker incarnation and admitted generation; both registered build/storage
threads must have joined successfully in order. The complete publication journal
must belong to that same storage-thread resource and owner, with acknowledgement
before thread-join observation. Root/components, organization, asset, revision,
filename, returned path, size, checksum and archive manifest must agree. Existing
revision heads are checked under their asset lock before being advanced.

The same versioned binding is saved with the job result, current asset and
immutable revision in the business transaction. It identifies the execution,
publication, storage resource and output revision, and fingerprints retained
publication, file-identity and thread evidence. The public binding includes no
raw nonce, storage path or user content. Fingerprints are not signatures and do
not independently establish that a file remained unchanged after the recorded
publication observation.

An accepted cancellation cannot turn into a successful output. Pre-commit failure
rolls back all business records together. Lost acknowledgement after a real
commit retains the accepted binding while the execution remains unresolved; no
automatic replay, file deletion or invented acknowledgement is performed.
Already executing work can finish after maintenance admission closes.

## Observed local acceptance

Forty-one new tests passed using real disposable PostgreSQL, the actual Studio
worker and actual generated ZIP archives. Cases cover new output and revision
binding, stale revision rejection, wrong job/owner/path/manifest/publication,
missing and corrupt evidence, unfinished/failed threads, acknowledgement loss on
both sides of business commit, cancellation during publication and six actual
PostgreSQL lock-contention cases (job/execution/publication through commit and
rollback). A pending-write control proves the validator does not autoflush.

Full backend Ruff and mypy on 283 application files passed. The isolated database
migrated through the existing `20260918_0056` head; this part adds no migration.
Full backend and repository acceptance, exact tested source fingerprints,
protected CI, merge, source synchronization and QA cleanup are recorded only as
observed in `docs/project/runtime/fr06c5d8b5-resume-20260918/`.

## Not closed by this increment

A business binding is a prerequisite for execution settlement, not that
settlement itself. Existing executions remain unresolved and continue blocking
host drain. Interrupted or post-crash attempts are not adopted. Identity-bound
post-crash disposition, final execution settlement, cancellation reconciliation,
other consumers, coordinated deployment and live host-drain acceptance remain.
No production restart, schema migration, vault transfer or Cloudflare change is
included. Earlier part receipts retain their historical scope.
