# FR-06: MCP2 command timeout containment, not historical reconciliation

Base: `fa3588cbd6b5d417e1c8867c72ad0b10cb53316b` (the current PR835 review head).
This independent correction targets the existing MCP2 command runner, not the previously refused initial-install authorization worktree, old terminal writes, C5D adapter or dependency changes. None of those refused effects is repeated here.

## Reproduced behavior

The tracked `ops/mcp2/server.py` was byte-identical to the installed MCP2 source when read (SHA256 `bedaed0d3f11a3b6b8c23d76bee1047bdcce757a773671aa51b35f5a41217115`). Its `subprocess.run(..., timeout=...)` implementation reports a timeout after killing/waiting for the direct child, but does not explicitly terminate the child's process group.

Two actual, self-expiring, disposable process tests reproduced a late write after the timeout response: one with a still-running launcher, one with an exited launcher whose child still held the output pipes. Both failed on the unmodified source; the test children exited naturally after writing an owned synthetic marker. This demonstrates a possible cause of uncertain command outcomes, NOT that these processes or this cause explain any particular historical FR06 run. No original execution transcript was recovered.

## Correction and boundaries

Each command now starts a new process session. On timeout only that invocation's process group is signaled once. Before signaling, `waitid` with `WNOWAIT` checks that the direct child remains waitable without releasing its PID; code does not poll/reap it first. A missing/already-reaped leader prevents signaling an unproven/reusable PID. The supervisor requires Linux with default SIGCHLD handling and must be the sole reaper of its child. No PID is supplied by a public tool parameter.

Pipe collection and direct-child waiting after a timeout are bounded. Detached sessions, uninterruptible kernel I/O, third-party reaping and external provider effects are outside the group-containment guarantee. A detached disposable child is a deliberate positive control: it is not killed or claimed stopped. Ordinary successful commands retain their previous output/exit semantics; caught interruptions are not turned into successes. An explicitly empty environment no longer silently inherits the server environment.

Every timeout is returned as `outcome=unknown`, `automatic_retry=false`, even after a group signal and direct-child wait succeed. The diagnostic booleans report only the observed cleanup operations, NOT full process-tree drain, no prior effect, rollback or a durable terminal receipt. Work completed before the timeout is retained. This patch adds no bootstrap/installation/enrollment authority, no provider operation, no new tool, no installer invocation and no incident sanitation. It does not replace the canonical project journal or make the old missing terminal files exist.

## Evidence

Run: `docs/project/runtime/fr06-recurring-task-health/interactive-resume-20261002T112926080280Z-fa6292fe/`.
Source worktree: `/opt/AIOS-worktrees/fr06-command-timeout-20261002T113250Z-fa6292fe`.
The worktree retains `docs/project/runtime/mcp2-timeout-before.xml` (2 reproduced failures), `mcp2-timeout-after.xml` (34 PASS), and `mcp2-timeout-expanded.xml` (54 PASS). The final selected set includes the original MCP2 contract tests and 22 new tests for child containment, already-performed effects, detached sessions, signal ownership/order, finite cleanup waits, timeout limits, Unicode, shell routing and environment handling. The test MCP registration is synthetic; no real MCP restart or cloud call is made.

Full-suite result is separately retained in the run directory and must be read before acceptance. Smaller selections overlap and are never additive. PR835's pending checks at the time of this correction apply only to base `fa3588cb`, not to this new local patch. No workflow/threshold/skip rule is changed. The installed MCP2 file and live ingress roots are not modified.

## Independent references

Python subprocess documentation: https://docs.python.org/3/library/subprocess.html
Python waitid/killpg documentation: https://docs.python.org/3/library/os.html

Production release still requires accepted source review, authorized deployment, genuine common execution ownership, independently accepted initial installation/adoption and unresolved historical-effect reconciliation. C5D/C5E/C6 and the credential incident remain open; FR07 is unchanged.

## Final candidate verification

Complete root suite: **4063 PASS, 0 failures, 0 errors, 0 skips**, actual UID65534. Finished 2026-10-02T11:41:11.390902+00:00. JUnitSHA256 `a39f327bd1c9782dc6776c92c1fdd6c0f759afc3250e463c99baf6ea5856691a`. All2696 exported input files remained byte-identical to the source when this result was read; this documentation-only result is appended afterwards. The54 focused cases overlap the4063 and are not additional tests. No protected CI or live MCP installation is inferred from this local run.
