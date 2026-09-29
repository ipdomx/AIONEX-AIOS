# FR-06C5E2 — Durable memory-transition journal and verified recovery core

Base: C5E1 PR779 candidate `6d340519bc89b3c3421476566a3c090e1851fbd8`.
Prepared legacy operator remains at `13b76558f585f432acc831b6ad0448ee5909b5bd`;
it is not imported, installed or executed. FR-07 remains complete. C5E and FR-06
are not complete. This is source acceptance, not authorization to activate swap,
mount /tmp, install units, edit fstab or move production host state.

## Defect reproduced without privileged operations

The original `rollback_internal` function is retained verbatim in a test fixture.
Its dependencies are inert test doubles. Four negative controls demonstrate that
failed service commands, encrypted-swap shutdown, unit-file removal or legacy
swap activation can be ignored while the function returns normally. No real
systemctl, swapon, filesystem deletion or credential operation is invoked by
these negative controls. Their extraction hash is retained in runtime evidence.

The new core never substitutes an attempted command or return code for verified
restoration. There is no automatic rollback, apply retry, journal reset or
truncation path.

## Implemented protocol

`fr06c5_memory_transaction.py` provides typed plans, bound context and a locked
journal, plus one-step apply, read-only reconciliation, explicit reverse recovery
and full final-state verification. Nine memory-control step identifiers have a
fixed ordering; a plan may select a unique ordered subset. Before/after resource
fingerprints must differ. The binding includes exact source, boot identity,
closed maintenance operation and generation, host-state receipt, preflight and
boot-graph digests. Forward execution has an explicit maximum 900-second window.
Recovery does not silently adopt another boot or reopened/superseded authority.
Same-context explicit recovery can still be considered after forward expiry.

All journal path components are opened without following symlinks. The parent
and operation directories must be private and owned by the executing identity;
records and lock must be private, regular, singly linked files. A held flock
serializes writers. Directory and lock identities are checked again on access.
Each record is create-only, sequenced and hash-chained to the immutable plan.
Writes handle partial writes and synchronize both the record and its directory
before an effect is allowed. Corruption, duplicate JSON keys, sequence gaps,
unexpected entries, partial records, symlinks, hard links and identity replacement
stop progress rather than being discarded or treated as an empty journal.

Each effect has a durable intent and a separately observed outcome. A raised
exception, unverified result, lost outcome publication or process death leaves
that intent unresolved. Reconciliation only observes: it never invokes apply or
undo. Reconciling an interrupted forward step permanently halts forward progress
for that operation, regardless of whether its effect is found before or after;
only explicit recovery remains. Recovery proceeds in reverse order, and requires
current exact identity and operation ownership before touching a changed resource.
An uncertain undo also requires separate observation before any explicit further
recovery attempt. A final restored record requires every planned resource to
match its original fingerprint, including planned steps never executed.

## Executed tests and corrections

The focused suite includes real private-file writes, file identity checks,
fsyncs, independently reopened journals, flock contention and four real Linux
child-process SIGKILL boundaries: before and after apply, and before and after
undo. Only processes created by the test are killed. The recovered journal
refuses a repeat effect, accepts only an actual observation and verifies original
file bytes before recording restoration. This is process-crash testing, not an
actual machine reboot or power-loss durability test.

Fault-injection tests cover file and directory fsync failures, partial writes,
missing outcome records, command success without the required state change,
expired forward authorization, changed boot/generation/source/evidence, unowned
or replaced resources and incomplete/falsely finalized rollback. One added test
exposed an over-strict access-time comparison; the fix ignores read-induced atime
only, retaining inode, device, mode, ownership, link count, size, mtime and ctime
checks. The failing result is retained. No test/scanner rule was disabled.

Tests run as `nobody` with an exclusively owned disposable directory. Full root
regression uses a separately writable, hash-matched snapshot, not chmod/chown of
the production source. Exact counts, source hashes and exit status are recorded
under `docs/project/runtime/fr06c5e2-memory-journal-20260928/`.

## Explicitly excluded from this receipt

No production/kernel adapter or activation command is supplied by this module.
The adapter protocol requires resource-identity and ownership attestation; it
cannot prove a production mapper, mount or backing file merely by comparing
caller-supplied digests. Future integration must bind actual C5E1 underlay and
writer-quiescence proof, mapper/backing topology, memory reserve, secure key
lifetime, full host boot graph, actual command postconditions and verified
recovery across boot. The old unsafe memory operator remains quarantined.

The journal is a fail-closed crash/corruption record, not protection against root
or an actor able to rewrite all journal data and hashes. A journal with missing
or corrupt records requires operator investigation, not automated repair.

No production swapoff/swapon, cryptsetup, mount, fstab edit, service operation,
provider inventory or host-state move occurred. No prior blocked Replicate,
combined post-D10 verification or Telegram bootstrap request was retried. The
completed Backend, media workers, Telegram bots and observer are not redeployed.
C5D provider/resource drain and encrypted host-state cutover, C5E production
adapter acceptance and C6 final encryption verification remain separate gates.
