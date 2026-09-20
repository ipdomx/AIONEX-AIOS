# FR-06C5D8A2B4 — Acknowledged Studio filesystem publication journal

Base: PR #728, merged at `39048c4c4e4055a0c2bfd7d83d60a979eecc1a71`.
This increment is filesystem intent and local observation, not execution settlement.
No production database migration, container deployment, host cutover or vault
transfer is part of this source increment.

## Implemented boundary

An independent `studio_publications` table retains the exact execution owner,
worker incarnation, admission generation and storage-thread identity. It has no
business/execution foreign key capable of cascading away evidence. A unique
execution and thread resource prevent duplicate publication reservations.
Migration 0056 uses frozen DDL and exact reflected-schema comparison, supports
fresh bootstrap metadata, and refuses destructive downgrade.

The owned storage thread installs a context-local observer. Each request is
submitted to the original event loop with `run_coroutine_threadsafe`; the thread
waits for a committed acknowledgement, not a timeout or cancellation. Database
sessions never move between event loops. An unacknowledged event permanently
closes that observer to further mutation, including cleanup. The first failure
is retained if cleanup/evidence also fails.

Before filesystem mutation, the observer reserves the entire root/parent chain,
private staging name, final name, size and checksum. Each directory operation,
staging creation, write, no-replace link and staging removal has an acknowledged
intent. Observations bind pinned descriptors to device/inode, file kind, owner,
permissions, link count, size and timestamps. Ordered journal validation rejects
missing, malformed, stale, reordered or identity-mismatched observations.

An archive linked before a lost acknowledgement remains intact. Cleanup removes
only the identity-checked staging name, never the final archive. A journaled
`complete` means local publication was observed with one final link and staging
removed; it does not settle the execution or certify business commit, full-host
cleanup, production coverage or application-level acceptance.

The repeatable-read execution snapshot includes publication rows across all
generations, including orphan publications whose execution rows disappeared.
It exposes counts and identifiers, not filesystem paths or ownership nonces.
Both claim filtering and transactional registration refuse a job with retained
publication evidence even if its execution row was lost. Fresh jobs are not
starved behind such retained evidence.

Direct, unowned library calls keep their previous local-only publication behavior;
only owned Studio worker storage is journal-bound in this increment. Same-UID or
root actors able to maliciously mutate entries after validation remain outside
this cooperative-worker filesystem model. Post-crash deletion by inode number
alone is not implemented or authorized by this receipt.

## Observed local acceptance

The combined real PostgreSQL/thread/filesystem suite passed 203 tests, including
43 new cases. These include a real worker publication; acknowledgement loss
before effects and after an actual link/commit; 1/3/16 repeated caller
cancellations during an in-flight publication observation; partial-write
cleanup and first-error preservation; existing/replaced destination retention;
owner-component and stale-sequence rejection; migration repeatability and
no-discard downgrade; orphan evidence; and prevention of replay/starvation after
execution-row loss. Files and databases are synthetic and disposable only.

An initial expectation incorrectly counted the fixture's historical unverified
job as absent; corrected tests keep it in blocker counts. Compatibility fixtures
now create the new table. The snapshot isolation test checks all four actual
reads remain repeatable-read instead of its prior three-read count. Initial
failures remain in the runtime evidence; no production guard was relaxed.

Full repository, static quality, CI, merge, exact-main acceptance and cleanup
are recorded only when observed in the canonical Project Hub at
`docs/project/runtime/fr06c5d8a2b4-20260918/`. No pending check is a passed check.

## Remaining

Execution settlement and authorized cancellation reconciliation, identity-bound
post-crash file handling, proof that accepted business output matches retained
publication evidence, and release of genuinely settled blockers. Successful
thread return and local publication do not close these requirements. All other
FR-06 consumers, containment, coordinated deployment and host-drain gates remain.

Implementation references: Python 3.11 asyncio cross-thread scheduling and
cancellation contracts, and os descriptor-relative filesystem operations:
https://docs.python.org/3.11/library/asyncio-task.html
https://docs.python.org/3.11/library/os.html
