# FR-06 C5D: independent epoch-inventory core, not production acceptance

Status: isolated source work, locally verified; NOT wired into the live cutover.
Base: PR #835 head `87d52daee928e4faa9c20c360664517c8321c748`.
Worktree: `/opt/AIOS-worktrees/fr06-c5d-epoch-verifier-20261001T1512`.
The worktree suffix is a label, not a measured invocation timestamp.

## Why the earlier v2 patch is not accepted

The separately owned `fr06c5d-drained-topology-v2-20261001` worktree was read,
not changed. Its read-only success is insufficient for a production cutover:

* `topology()` selects the stopped services by service name and exit code,
  without binding their image/restart epochs to the raw accepted stop receipts.
* It returns the restart policy but does not require `no` for drained services.
* The Docker listing filters to the project, and the generic stopped-container
  `continue` silently ignores unknown stopped containers. This is not explicit
  acceptance of exactly the four historical successful oneshots.
* Inspection/list identity-set equality was removed. Count equality is not a
  bijection between listed and inspected container IDs.
* Source/boot/current authority and component evidence are not inputs to that
  topology function. Its containing production `evidence()` gate is not a
  replacement for raw, freshly bound full-host closure validation.

No previously refused merge, stage/commit of v2, cleanup or pytest suite was
retried to perform this independent work. Existing worktrees remain untouched.

## New pure core

`scripts/security/fr06c5d_epoch_inventory.py` performs no Docker, database,
network, file or host operation. It revalidates raw graceful-stop before/after
bundles using the existing pure acceptance implementation, checks the raw
per-service stop receipts AND their hash commitments, and compares exact live
container ID, image, restart count, restart policy and clean terminal state.

The fixed inventory must contain a bijective whole-host listing and inspection
of exactly 40 identities: 33 running, three drained, four explicitly named clean
oneshots. Unknown, duplicate, replaced, partially observed, non-project or
mislabelled containers are rejected. Source, boot, closed schema-8 operation and
generation, UTC freshness and receipt commitments are explicit typed inputs.
The returned immutable inventory always has `full_host_closure=false` and
`production_activation_authorized=false`.

A future accepted adapter must obtain the unfiltered whole-host inventory,
real clock and current authority, safely load authentic receipts and derive the
binding from accepted evidence while exclusive execution ownership is held.
This pure core cannot independently establish capture provenance, file custody,
protected CI, source deployment, Studio/Coturn drain, writer/underlay closure,
maintenance authorization or boot/recovery. No such acceptance is claimed.

## Actual isolated verification

New independent suite: `tests/test_fr06c5d_epoch_inventory.py`.
The first 79 tests passed. Additional malformed-input cases reproduced seven
failures; four were inconsistent error handling and three admitted malformed
Cloudflared healthcheck definitions. They were fixed in this new core.

Final JUnit result read at `2026-10-01T15:11:58.228674+00:00`:
88 tests, zero failures, zero errors, zero skips. Synthetic records and clock
only; no production snapshot was represented as a synthetic test result.

Evidence retained inside this worktree under
`docs/project/runtime/fr06-recurring-task-health/interactive-epoch-verifier-20261001T1512/`:

* `malformed-before.xml`: 88 tests, seven failures; SHA-256
  `fc437f2f20c8bcbca5bffa61dde2ef9284994c2e46131f46e555a47089e2000f`.
* `independent-final.xml`: 88 tests, no failures/errors/skips; SHA-256
  `f185e3b42a647fc1e57666954a6700f0e61fd76f2d0804582da7bb7bc102c38e`.

Core SHA-256:
`884fc729f3bab7d33b653e68cce19d747d52f653b127e2e09206180e344afab4`.
Test SHA-256:
`1c8427444de07e01d66b4c4e8e2ffefb914d8ed9993c918f3b3b29c7475c3ec6`.

The prior C5D regression suite and protected GitHub CI were NOT executed for
this new source. This result does not accept the earlier v2 patch or close C5D,
C5E, C6 or FR-06. Do not wire or activate it without reviewed integration and
all required protected current-head checks. A source merge is not deployment.

## Observability limitation and continuation

The attempted new interactive started-receipt/journal operation was rejected
by the platform before execution. Do not claim it was saved or label this work
scheduled. New evidence above is actual isolated test output, not a scheduler
heartbeat. The prior 13:01/13:58 scheduled and 14:53 interactive runs retain
uncertain terminal status unless their effects are independently reconciled.

Production source remains on the previously observed `7779f740...` with the
untracked malformed `$dir` evidence preserved. No source sync, service action,
provider lookup/settlement, activation authority, swap/tmp or reboot occurred
in this independent work. The original #835 queue must not be duplicated or
merged through a refused route. Shared writes require accepted exclusive
control, and any denied effect remains subject to its normal safety/approval
resolution rather than an alternative tool, branch or task.
