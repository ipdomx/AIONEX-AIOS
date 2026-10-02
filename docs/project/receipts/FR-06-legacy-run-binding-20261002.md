# FR-06: legacy run binding, source correction only

Base: `41b42aea51650e0838f8d11e34e43cbdac21e729` (PR835).
Interactive invocation: `interactive-bootstrap-audit-20261002T052532Z-64a2b25a`.

## Reproduced defect

The prior `_event_run` implementation searches for the entire run-directory name
inside the event ID. Historical events use `fr06-scheduled-start-<suffix>` and
`fr06-scheduled-terminal-<suffix>`, while their actual directory is
`scheduled-<suffix>`. Those events returned `(None, None)`. A synthetic executable
regression demonstrated that `verify_bundle` could then accept otherwise complete
bootstrap input containing a legacy start with no terminal receipt.

Six new regression cases failed before the change: legacy start/end recognition,
a terminal carrying both file references, an unfinished legacy run and two wrong
identity cases. The correction recognizes exact historical role/phase/suffix
identities, requires the correct fixed receipt reference and rejects conflicting
roles/phases/noncanonical paths. Unknown effects are not reconciled by this code.
No authority, production installation, launcher, privilege predicate, protected
workflow, minimum CI check or drain requirement is weakened or issued.

## Actual verification

* New six regressions plus existing enrollment/installation suites: 125 passed
  in the successful MCP response before the later extended-test write refusal.
* Existing execution guard/source operator/source-sync suites: 156 passed;
  `existing-execution-regressions.xml` retained.
* `history-binding-before.xml` retains the six pre-fix failures.
* `source-test-boundary.json` binds the unchanged tested source/test bytes.

These are selected local suites, not the complete root suite or protected CI for
this correction. Production/shared action authorization remains false.

## Current read-only inventory, not effect reconciliation

An independent uncommitted audit prototype inspected 533 canonical events,
opening only events.jsonl and fixed started.json/terminal.json names. The entire
known credential-incident directory was excluded. It identified 10 complete
file/event accounting pairs and 24 runs needing accounting review (including the
current in-progress audit, missing bindings and the incident exclusion). Those
24 are NOT asserted to be 24 dead workers or 24 unresolved production actions.
Five event bindings were ambiguous/unbound. Four specifically requested historical
scheduled runs (13:01,13:58,16:01,21:57 UTC on October 1) still lack terminal files.
The original execution transcripts were not recovered; later reports are not a
substitute for those traces and cannot prove that no external effect occurred.

The audit prototype and its planned extended tests are NOT part of this source
commit: the combined expanded-test write was denied before execution; metadata
confirmed the new test file absent and the original six-case file unchanged.
That denied operation was not rerouted. The prototype is unreviewed and must not
be used as a live enrollment/authority issuer.

## Evidence and outstanding acceptance

Evidence directory (server):
`docs/project/runtime/fr06-recurring-task-health/interactive-bootstrap-audit-20261002T052532Z-64a2b25a/`.
`prebootstrap-inventory.json` contains bounded sanitized diagnosis only.

This commit is local only until independently published and accepted through the
normal protected source path. PR835's previous successful checks do not accept
this new commit. Current main is still `7779f740a81d4fae2167c8441218b69e54cf56f5`
with the untracked literal `$dir` preserved. The common execution directory,
actual role launchers/enrollment and independent bootstrap remain absent.
No merge, sync, install, provider call, host migration, swap/tmp change or reboot
occurred. C5D/C5E/C6 and the credential incident remain open; FR07 is preserved.
