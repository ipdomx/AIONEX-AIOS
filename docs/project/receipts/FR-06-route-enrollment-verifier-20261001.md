# FR-06 — fixed-route enrollment verifier (local source, not live enrollment)

## Exact starting point

Interactive run `interactive-enrollment-20261001T165402816497Z-3a814e76` read the
canonical README/report/state/event journal before work. Production HEAD and
origin/main remained `7779f740a81d4fae2167c8441218b69e54cf56f5`, with the preserved
untracked literal `$dir` directory. PR835 remained OPEN/CLEAN on
`87d52daee928e4faa9c20c360664517c8321c748` when observed; its required checks were
successful. That PR is still the canonical shared queue, not superseded here.

This isolated worktree starts from local source-dispatch commit
`3005fd32056a8899c63b33091fe53562b2c33e2c`. The earlier worktree and all other
incomplete runs were preserved. Neither its source nor the work in this receipt
has protected-CI or production acceptance.

## Implemented integration

The previously absent `fr06_execution_enrollment.py::verify_installed_routes`
interface is now implemented and connected to the Native source dispatcher.
It is a read/verify-only module: no installer, issuer, shell fallback, production
lifecycle, credential reader, provider client, cleanup or replay operation.

The external enrollment and bootstrap evidence must match exact source, boot,
operation, integer generation, fixed task, fixed root and kernel lock identities.
A checksum reference is recomputed over actual bounded evidence bytes. The three
roles require separate retained start/terminal/probe records bound to exact
canonical journal events, actual chronology, launcher identity and unique
challenges. Prompt edits, an enabled scheduler, role labels alone, timestamps
alone and `approved: true` are not accepted enrollment data.

The bootstrap binds an actual canonical journal prefix. Unfinished known runs,
missing terminal files, unknown outcomes, unsupported legacy schemas and invalid
metadata block instead of being relabeled completed. Historical file pairing is
run accounting ONLY, not proof that a provider/host effect was reconciled. Actual
pre-guard action reconciliation remains mandatory in the independent authorized
bootstrap admission. This module does not provide that authority or infer it
from a terminal receipt's claims.

An explicit hash-bound metadata-only quarantine can preserve a historical
placeholder event without making it acceptance. The correction scope is exactly
`invalid_metadata_only_not_effect_reconciliation`; it cannot target a valid run,
clear a real intent, edit history or invent a missing terminal. The original
malformed record remains in the journal. Source hygiene and unknown-effect gates
are independent and still apply.

Native verification reads only fixed filenames with no-follow descriptor walks,
owned metadata, single-link regular files, strict size bounds and inode/size/time
readback. No caller-supplied raw filename or incident diagnostic file is read.
The source dispatcher additionally verifies installed code and launcher bytes
against reviewed Git objects. The enrollment verifier is now included in the
source self-update boundary, not silently changed during ordinary source sync.

Every verification also runs three fresh unpredictable kernel-contention
challenges through the installed role launchers. The new `enrollment_probe` mode
opens an EXISTING private lock and attempts a nonblocking flock. It creates no
lock, journal, receipt or directory and never calls merge/sync/provider/lifecycle.
The parent either holds a temporary probe lock or reuses its actual typed,
same-process ExecutionGuard without unlocking it. A guessed/stale/mismatched
child reply, wrong PID/role/challenge/inode or absent real contention is rejected.
An uninstalled candidate CLI refuses before touching a live guard.

The role-acknowledgement aggregation window is two hours, matching two hourly
opportunities. The first draft's 15-minute window was reproduced as incompatible
with an hourly primary/watchdog cadence and corrected before acceptance. This
is NOT a change to Studio/Coturn/activation freshness; every current native
verification still performs new kernel challenges, and all production drain,
source/boot/authority and action-specific controls remain independent.

## Local acceptance only

Final selected suite: **370 tests, zero failures/errors/skips**:

- 111 enrollment/probe/evidence tests.
- 68 source-dispatch/launcher tests.
- 11 source-sync binding tests.
- 77 execution-guard tests.
- 88 inherited epoch-inventory tests.
- 15 original project_hub tests. The separate uncommitted 33-test hub repair is
  not included in this source or count.

Real disposable Linux child processes contend on the same inode for all three
role routes. Additional Native evidence-file plumbing tests execute three real
TEST-ONLY launcher scripts while verifying actual private fixture files and lock
ownership. Git/authority/boot/role-enrollment inputs in those Native tests remain
SYNTHETIC. They are not real scheduled invocations, real enrollment, GitHub CI,
production installation or evidence that active external clients have adopted
the protocol. The protocol does not authenticate a human role label or isolate
malicious root. Real ingress adoption requires the independent reviewed rollout.

Retained before-fix artifacts include 12 newly reproduced cases (numeric types,
clock types, journal/terminal binding, duplicate challenges and fake guard), one
hourly-cadence failure, and one metadata-quarantine compatibility failure. They
are preserved, not overwritten or counted as passing. A test-file write reported
an error with an initially unknown outcome; subsequent explicit file metadata,
AST, contents and hash inspection found the intended file. The write was NOT
blindly replayed, and tests ran only after reconciliation.

Evidence directory:
`docs/project/runtime/fr06-recurring-task-health/interactive-enrollment-20261001T165402816497Z-3a814e76/`

- `enrollment-final.xml`: `25a5317bac14136a41117465d27d4c5aab91358dc1da0c1340cfbd127d5489eb`
- `enrollment-negative-before.xml`: `fff7c57e4d7e9409bdab1b780ab388990dba2439019d621f07a43704945a9820`
- `enrollment-cadence-before.xml`: `b4993a03295fd59a1137b38478b76ed495b478a40403687a2807434c84e4efca`
- `enrollment-quarantine-before.xml`: `420ceb6cbdda2fdb593dd4593fcea6c7b613c3f489776698be54f543020cc82d`

## Remaining gates — no self-enrollment

No bootstrap/enrollment file, live role acknowledgement, installed launcher or
live execution journal was created. No production code was replaced. The
operator cannot merge/install/authorize itself from these local tests. Source
submission, protected acceptance, independent authorized bootstrap/ingress
adoption and actual prior-effect reconciliation remain required. Missing or
unsupported real records must be reviewed, not fabricated or replaced with test
fixtures. Historical refusals were not retried via the new mode or another route.

C5D historical stop adaptation and raw composite drain acceptance, C5E production/
writer/underlay/boot integration and C6 recovery remain separately incomplete.
The sensitive incident file was not opened, copied, printed, sanitized or
uploaded. Credential rotation and usage review are unverified. The preserved
untracked `$dir` directory was not removed; metadata quarantine is not cleanup.
FR-06 remains in_progress and FR-07's accepted state must remain unchanged.
