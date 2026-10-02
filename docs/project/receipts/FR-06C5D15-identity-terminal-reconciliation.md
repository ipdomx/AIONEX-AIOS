# FR-06C5D15 — fail-closed Identity Media terminal reconciliation

## Scope

This source-only part addresses two production Identity Media rows that are already locally terminal as `status=failed` with `completed_at` set and no active lease, while their stored Replicate `provider_state` remains `starting`. The production read-only observation on 2026-10-01 found exactly two such rows, both from `voice_clone`, each with one primary provider job and no secondary job. Only execution identifiers, row versions, status fields and SHA-256 digests of provider job identifiers were retained; raw provider job identifiers and credentials were not recorded.

The operator does **not** submit, retry, cancel, download, or otherwise mutate provider work. It permits one read-only Replicate prediction lookup for each frozen candidate and accepts only the provider terminal states `failed` or `canceled`. The only possible production mutation after protected source acceptance is an exact row-locked correction of the local `provider_state` plus a version increment and audit event. The business `status=failed` remains unchanged.

## Journal and recovery contract

A root-owned operation-private journal binds the exact closed schema-8 maintenance operation/generation and exact clean protected source commit. The candidate set is frozen once in a create-only fsynced session record. Each local settlement has its own create-only intent before the database transaction and an accepted receipt afterwards.

A previously written settlement intent is never replayed. If the exact expected database effect is already observable, the operator may record reconciliation without repeating the settlement; otherwise it halts. A crash after one candidate is accepted no longer causes the remaining session to be reconstructed from the smaller current query result: reopening uses the original frozen candidate set, verifies already accepted rows, and continues only candidates for which no settlement intent exists. New candidates appearing after session creation are not silently adopted.

## Focused verification

- 9 new focused tests pass for exact single-settlement behavior, partial-session restart, no replay after unresolved intent, rejection of source drift, rejection of tampered/duplicate session bindings, refusal to silently adopt a late candidate, and a static boundary proving the provider reader contains no create/cancel/download call.
- The new tests together with the existing root Identity Media contract and C5D12 maintenance-resume tests pass 25/25.
- An attempted mixed invocation including backend tests could not collect because the host Python environment lacks SQLAlchemy. This is an environment/setup result, not a source acceptance claim; protected CI remains authoritative.
- Python bytecode compilation and whitespace/error checking pass for the new source and test files.

## Production boundary

No provider lookup, database settlement, maintenance transition, container restart, swap or mount effect is performed by this source receipt. The two stale rows were observed read-only only. The operator must not run on production until this exact source passes protected CI, merges into protected main, the live source is synchronized cleanly, and the exact maintenance authority is revalidated.


## Interactive continuation: transactional authority race fixed

The staged patch from the scheduled 11:00 run was retained byte-for-byte before review (SHA-256 `3aac6c50bb9cbfab050620e1b50b1009f4952ca996a6561cd300eb24fad81464`); its original worktree was not edited. A separate successor integrates it on the current-main consolidation.

Review reproduced five failures by executing the original embedded settlement program with declared database doubles: it did not read maintenance inside the business transaction and accepted a changed authority. The correction now acquires the existing PostgreSQL shared authority lock in the SAME transaction as the execution row lock, validates closed schema8, operation and generation before any business write, retains the lock through commit, and records operation/generation in the audit. Current source is rechecked before provider observation and settlement. No admission scope, caller rights, provider mutation or retry is added.

The corrected program passed the five new control-flow regressions; the full selected integrated suite passed 145 tests, with no failure/error/skip. The previously recorded suites overlap and must not be added together as unique coverage.

A separately owned PostgreSQL 16 laboratory executed the exact embedded settlement program against real application models and the existing real authority reader. Six cases passed: open authority denied, generation change denied, operation change denied, successful same-authority commit with bound audit, version-CAS denial of repeated settlement, and a real PostgreSQL wait proving reopening cannot obtain its exclusive authority lock until settlement commits. No row locks or transactions were mocked in this laboratory. Provider calls were zero; all tenant rows and credentials were synthetic, the Docker network was internal with no published ports, and no production configuration or volume was mounted. All three owned containers and the network were removed and absence verified.

The first laboratory setup failed before connecting because the disposable SECRET_KEY was missing; that log is retained and is not counted as a passed case. The corrected isolated run passed all six. Embedded settlement program SHA-256: `d5a779bb0166f60f22d5605987dced7420034a52159d2d157551443caf94fbd9`. The executable lab fixture is retained under `tests/fixtures/fr06c5d15/settlement_postgres_lab.py.txt`. Logs, XML, baseline failures, result and cleanup receipts are at `docs/project/runtime/fr06-recurring-task-health/interactive-resume-20261001T112633683536Z/`.

These are source and isolated-database results only. No production provider lookup or row settlement occurred, and no C5E/C6 activation or recovery is claimed. Protected current-head CI remains a separate mandatory gate.
