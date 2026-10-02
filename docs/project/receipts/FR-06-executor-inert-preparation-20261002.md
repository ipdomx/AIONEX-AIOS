# FR-06: inert preparation half of initial executor installation

Parent source: `aa96108419adca12a382033c4702b36ffe7a1566`, including the local legacy-run-binding correction. This is independent new source work, NOT the previously denied prebootstrap-auditor test extension. That prototype and its absent expanded tests were neither imported nor retried.

## Scope and non-claims

`scripts/security/fr06_executor_preparation.py` supplies the previously missing **preparation half**, not an installer, bootstrap attestation issuer, role-adoption mechanism or history reconciler. It reads six fixed Git blobs (three code modules and three role launchers), verifies the actual checkout's commit/bytes/modes twice, and writes an inert package under a preexisting owner-private store. Every staged file is mode0400, including launcher text; package directories are0700. There is no activate/install/enroll/merge/sync command, no live lock creation and no provider/service/host action.

The status is `prepared_not_installed`. `installed`, `enrolled`, `exclusive_execution_accepted`, `historical_effects_reconciled` and `production_activation_authorized` remain false. Package bytes and a matching SHA256 are NOT evidence of protected source acceptance or live authority. Inspection proves current readable package contents, not the completion or absence of an earlier external effect.

## Actual file behavior

The preparation operation UUID is claimed by exclusive directory creation and never adopted/replayed after a failure. The intent is file- and directory-fsynced before payload writes. All writes are create-only, short writes are completed, and partial material is retained. File reads use bounded no-follow descriptors and reject wrong owners, links, special files, byte/mode changes and identity changes during a read. The source Git reader uses fixed read-only commands and does not inherit GIT_DIR/config overrides or credentials. It never scans runtime evidence or environment files.

Inspection uses a shared nonblocking kernel flock on the exact package directory; creation holds the exclusive lock. It verifies the precise allowlisted file set and cannot turn an extra enrollment file, a rehashed forged payload, or a true authority flag into success.

The first54 tests passed. Three additional permission-drift cases then reproduced an actual issue in this new uncommitted source: failure was correctly reported, but ready.json could already have been written before the changed directory permissions were detected. Preparation now rechecks store/package/payload permissions and identities immediately before that marker, and after capture. The three failing cases are retained in preparation-metadata-before.xml; they are not production failures.

## Verification performed

`tests/test_fr06_executor_preparation.py`:60/60PASS as UID0 and separately60/60PASS as UID65534. These are the same tests under different privilege profiles, not120 distinct cases. They use real Git, file syscalls, independent processes and kernel flock on disposable owned paths. Competing processes produced one package and one already-claimed rejection. A child killed after its fsynced intent left only the intent and could not be automatically replayed. No live privileges or production authority were modeled as actual acceptance.

An actual candidate-source CLI preparation was also executed in the isolated worktree: six byte-identical payload files for parentaa961084, all non-executable, with manifestSHA256 `2b336a52561d623bb139b2828aa79fb108d8f64a057251ae521e194bb3d3e74e`. Its operationUUID is `47cd3ed6-68fd-4131-b3ee-8b8538342101`. Both live executor directories remained absent after this experiment.

Full root suite:3978PASS, zero failures/errors/skips, actualUID65534, finished2026-10-02T06:17:40.293527+00:00. JUnitSHA256 `2fc0b996de5cb8eb7d7ebadbae5a0b6d7c81442bd42ea764d79034bfdd66b108`. All2692 exported source files matched the worktree before this documentation-only result update. This run includes the inherited legacy-run fix and the new60 cases; smaller selections overlap and are not additive. The long-call return reported an existing create-only log; the saved XML, exit0 result and finished log were reconciled instead of starting another suite. There is no protected CI for this new source, no push, and no production installation.

## Retained evidence and blockers

This interaction's server evidence directory:
`docs/project/runtime/fr06-recurring-task-health/interactive-bootstrap-stage-20261002T060514Z-8056e11f/`.

It contains genuine started receipt/event, preparation-first.xml, preparation-metadata-before.xml, preparation-root.xml, preparation-nonroot.xml/txt and inert-package-result.json. The package itself is under this worktree's `docs/project/runtime/executor-preparation-lab/stage/47cd3ed6-68fd-4131-b3ee-8b8538342101/`.

Do not infer this interaction's terminal from this source receipt: read its actual terminal.json and canonical journal entry. PR835's successful head41b42aea does NOT accept the inherited aa961084 or this new work. Source review and independently authorized installation/adoption remain separate. The four October1 scheduled runs at13:01,13:58,16:01,21:57UTC remain uncertain; conversation retrieval returned later summaries, not original execution traces. No missing end receipt, image, replay claim, elapsed time or authority was synthesized.

C5D/C5E/C6, security-incident remediation and final release are not closed. FR07 is preserved. No old denied commit, adapter mutation, auditor test write, host action or terminal write was retried by this preparation work.
