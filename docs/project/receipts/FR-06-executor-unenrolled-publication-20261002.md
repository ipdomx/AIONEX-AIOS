# FR-06: initial installation file-publication engine, without enrollment

Base: `541da0dc05b92b52bff77a2498e537bffc5242fe`, inheriting the legacy-run binding fix `aa96108419adca12a382033c4702b36ffe7a1566`.

## What this source adds

`fr06_executor_installation.py` completes the **file-publication transaction** after the inert package preparation. It creates a new empty execution lock and receipts directory and publishes the three exact launcher files to two caller-designated roots through Linux `renameat2(RENAME_NOREPLACE)`. It requires a dedicated preexisting private installation journal, same-filesystem publication, a previously prepared package matching the exact source, and a mandatory independent initial-install authorization reader.

This is a library, not a live installer invocation, native authorization adapter or bootstrap issuer. There is no CLI, default permission or built-in callback claiming that source approval, an installation window or exclusive ownership exists. The production caller must supply those independently accepted checks. Tests use an explicitly synthetic admission callback and owned temporary paths. They do NOT establish protected CI, actual role adoption, old-run reconciliation or authorization for production. The unresolved historical runs are unchanged.

No enrollment.json or bootstrap-evidence.json is created. The existing dispatcher still refuses merge/sync without authentic enrollment. No existing source module is overwritten, no Git reference changes, and no service, provider, database, swap, temporary-filesystem or reboot operation exists in this library. A package or files-installed receipt is not execution authority.

## Transaction and failure behavior

The journal is single-use even if another operation UUID is supplied. A real nonblocking kernel lock excludes concurrent installer invocations using the same journal; it is NOT the future common executor lock or proof that other agents have adopted it. All records and file data are fsynced. Candidate inode identities and hashes are retained before each namespace effect. Both roots and all retained journal records are rechecked after each durable intent and immediately before the next publication. Existing or late foreign targets are never replaced. No weaker rename/copy fallback, automatic rollback, adoption or replay is used. Failure or child-process death preserves partial installation and its original intent.

Initially42 tests passed. Nine additional controlled drift cases reproduced defects in this new, uncommitted engine: candidate changes during intent recording were detected only after publication, and rewritten candidate-history records were not revalidated. The engine was corrected before acceptance. All51 cases then passed. Twelve integration cases were added through the existing source dispatcher, with synthetic installed identity but real file ownership, proving missing/forged enrollment rejects both source actions for all three roles before any GitHub/authority/effect call.

## Actual verification

Focused engine:63/63PASS as UID0. Preparation+first51engine cases:111/111PASS as actual UID65534. Complete source suite: **4041 PASS, zero failures/errors/skips, actual UID65534**, including all63 engine/dispatcher cases. Finished2026-10-02T06:46:10.115982+00:00; JUnitSHA256 `2c17963073c75e168a9ec9533f1667988459680ffc93ef958b6833561f984bb7`. All2695 exported files matched source bytes before this documentation-only update. Counts overlap and must not be added. The long-call response reported that the create-only log existed; the saved completed XML, exit0 and finished log were reconciled instead of replaying the suite.

The tests perform real Git and Linux file syscalls, atomic no-replace publication, competing processes, and SIGKILL of an owned child immediately after the first namespace change. They demonstrate actual kernel contention on the newly published lock, but this is NOT a real scheduled/interactive/watchdog enrollment challenge.

Run evidence: `docs/project/runtime/fr06-recurring-task-health/interactive-bootstrap-install-20261002T063325Z-09941054/`. Failed first-boundary XML is retained separately from corrected results. Production paths `/var/lib/aionex/fr06-executor` and `/usr/local/libexec/aionex/fr06` have not been written by this interaction. PR835's checks for41b42aea do not accept this new library or its inherited local commits.

Remaining: protected source submission/review; independently authorized native installation caller and real invocation; authentic role adoption and old-effect reconciliation; C5D/C5E/C6 and the separate credential incident. No old denied auditor tests, dependency commit or host effect was retried.
