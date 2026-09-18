# FR-06C5D7B8 — joined scan runtime source acceptance

Baseline: accepted main `0e26a756b1a0486ebf8de312d3fa51678d226f7b` (#720).
Draft base: `9dce28b6d815cd7b6a4a779e251f256d1b106d49` (#722).
This supersedes the historical draft-blocker section of FR-06C5D7B6, not its
production, host-drain or legacy/ambiguous-work boundaries.

## Corrected blockers without weakening gates

The independent acceptance snapshot preserves the exact three previously edited
runtime files after SHA-256 comparison. Four bare-pass branches now explicitly
continue observation or retain an unresolved result. A signal race is not process
cleanup, and swallowing an operation error cannot substitute for a completed join.
No zero-dead audit exception, skipped gate or forced merge is introduced.

A complete local backend attempt exposed a pre-existing D6 test-observation race:
`pg_blocking_pids` reported a blocker while the simultaneously sampled activity
wait field was not yet `Lock`. The bounded observer now keeps polling until BOTH
facts prove the lock barrier. It does not treat a missing wait event as success,
change the deadline or remove the one-waiter assertion. Three deterministic
regressions exercise initial null, Client and IO observations before a real Lock
observation. The original failed run remains retained separately.

## Measured acceptance and scope

The complete root suite passed **1681 tests**, as uid 65534 in a separate writable
source snapshot with the host toolchain. The earlier thin-container run with
missing host executables remains a failed harness attempt, not a product pass.
Ruff on all backend application and test files passed; mypy passed all **275**
application source files. The complete migration to `0053` passed on an unexposed,
disposable PostgreSQL instance before the full backend run.

Explicit opt-in integration file:
`web-dashboard/backend/tests/security_acceptance_lab/fr06c5d7b_real_zap.py`.
It passed **three** cases combining real PostgreSQL transactions, the actual
worker and heartbeat, real joined process/thread/workspace resources, and an
isolated ZAP 2.17.0 JVM with a synthetic HTTP target. Passive and active cases
settled five resource records each, joined operation and supervision, removed
workspaces, observed empty engine inventories, released the exclusive database
engine fence, and rejected a second claim. Database ownership/intent was checked
before each of 22 and 29 real engine requests respectively.

The cancellation case withheld natural-completion observation after a real
acknowledged submission. The actual cancellation endpoint returned intent; a real
stop acknowledgement did NOT release the durable engine fence. The execution
remained unresolved and non-replayable. The disposable daemon was then destroyed
for QA cleanup without manufacturing a settled registry observation. Per-case
private schemas were confirmed removed. The HTTP serving threads were joined.

This uses a stated synthetic executor to exercise worker/resource composition;
it does not certify production target authorization, the entire scanner catalog,
or all ZAP active rules. Active QA enables only real rule 40012 on the internal
synthetic target. No host ports, production credentials or external targets are
used. Ordinary CI does not auto-collect this explicit real-daemon acceptance.

## Exact-head merge gate and retained evidence

The full backend result, complete protected PR checks, exact merge-tree match,
post-merge main checks, cleanup and source synchronization must be resolved from
`docs/project/runtime/fr06c5d7b8-20260918` and the canonical append-only journal.
This source receipt is not a prediction of a running workflow's outcome. No merge
is authorized while any required exact-head check has failed or is unfinished.
All source application/test files are bound by the retained SHA-256 manifest.

The previous b6 full run was recovered as exit zero on its older source and its
cleanup was separately verified; it is not substituted for final-tree acceptance.
The b7 root and backend failures are retained with their exact logs. Final success
does not rewrite those attempts.

## Production and remaining parent boundaries

This is a source acceptance part only. There is no production container rollout,
production database migration, vault transfer or Cloudflare change. Neither a PR
merge nor healthy old containers proves deployment of this code. Production ZAP
containment, legacy/ambiguous executions, complete host admission/drain coverage
and the later FR-06 cutover still require their own evidence. Full-host closure
remains false, and FR-06 and the final release remain in progress.
