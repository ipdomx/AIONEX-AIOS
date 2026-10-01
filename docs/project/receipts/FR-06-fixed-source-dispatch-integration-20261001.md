# FR-06 — fixed source-dispatch integration, local review candidate

## Identity and status

Interactive run: `interactive-integration-20261001T163237396620Z-fc60d209`.
Parent local commit: `db8ce0ac327bd899ab8316ab667c8610fb73bd11`, retaining
`eb17d645a73ce3112cf508bc67bd7a7786d16d92` and PR835's source ancestry.
Worktree: `/opt/AIOS-worktrees/fr06-fixed-source-operator-20261001T1632-fc60d209`.

This is an isolated SOURCE integration and test receipt. No source was pushed,
no PR was created or merged, and no production fast-forward or deployment was
performed. It is not an accepted installation or a successful scheduled run.

Live initial reads at 2026-10-01T16:31Z found production HEAD/origin-main at
`7779f740a81d4fae2167c8441218b69e54cf56f5`, with the already-existing untracked
literal `$dir` directory preserved. PR835 remained OPEN/CLEAN on
`87d52daee928e4faa9c20c360664517c8321c748`, with all eleven required current-head
checks successful. The current branch rules endpoint returned strict protected
checks and the normal PR rule; these are observations, not authority to replay a
previously refused merge. PR835 remains the canonical queue.

## Implemented connection

The three **source-only** launchers `aionex-fr06-primary`,
`aionex-fr06-watchdog` and `aionex-fr06-interactive` route to the SAME fixed
`fr06_source_operator.py` and `/var/lib/aionex/fr06-executor` guard namespace.
They supply their fixed invocation role last and expose no arbitrary shell,
repository, guard-directory, bypass or force-reset option. They were NOT copied
to `/usr/local/libexec` and are not installed. The live source dispatcher was
observed absent from `/opt/AIOS` at16:46Z.

The dispatcher connects current repository observations, installed-route checks,
the actual process-bound guard, durable intent/result recording and fixed native
source merge/fast-forward operations. GitHub endpoints are explicitly bound to
`github.com/ipdomx/AIONEX-AIOS`. A normal merge includes the exact PR head and
never an admin/auto-merge/bypass setting. Acceptance checks every currently
required app/context on the requested head, with a minimum set preserving the
eleven security/release checks, the current base and strict up-to-date rules.
Required reviews cannot be replaced by missing review metadata.

Source sync separately checks the observed merged PR, exact remote-main checks,
clean local `main`, forward ancestry and the fetched target. It performs no
reset, cleanup, prune, force-push, deployment or submodule update. Existing Git
hooks or hook configuration cause refusal; they are not disabled or bypassed.
Automatic Git maintenance is disabled only for the fixed source transfer, not
security checks. A changed dispatcher requires separate reviewed enrollment,
not in-process self-update.

### Distinct synchronization binding

The original guard could describe only `source_commit == main_commit`. After a
remote merge, equating the still-old server with the new remote head would be a
false observation. The new `SyncBinding` keeps `source_commit`, independently
read `local_main_commit` and remote `main_commit` distinct. It is valid ONLY for
`source_sync` to that exact remote target. Ordinary maintenance bindings remain
strictly equal. Ancestry and exact-main CI are independently checked by the
fixed caller while the same lock is held; the binding itself asserts neither.

Any change after intent, refused/unknown command, lost response, receipt-write
failure or post-effect authority drift leaves uncertainty, never automatic
replay. Native command errors do not expose stdout/stderr. Owned command process
groups are joined/bounded on timeout; the timeout is still not a no-effect proof.
The three-service inspection helper and `Config.Env` are never serialized.

## Local evidence and scope

Final selected suite: **259 tests, 0 failures, 0 errors, 0 skips**:

- 68 source-dispatch/launcher/integration cases.
- 11 distinct source-sync binding cases.
- 77 existing execution-guard cases.
- 88 inherited raw epoch-inventory cases.
- 15 ORIGINAL project_hub cases. The separate uncommitted 33-test hub repair is
  not part of this tree or this count.

The suite exercises real local Git clone/fetch/fast-forward in disposable
repositories, preservation of unrelated work, diverged history without reset,
hook refusal without executing or deleting the hook, native subprocess timeout,
real parent/child lock contention, and all three synthetic caller roles.
GitHub responses, maintenance context and enrollment in integration fixtures are
synthetic. No GitHub write, application database, Docker state or provider was
exercised by those tests. Synthetic scheduled/watchdog labels are NOT live task
execution receipts.

The first sync-binding interface suite failed ten cases because the new binding
was absent; this is one missing integration contract, not ten production defects.
A later source-operator negative suite reproduced seven gaps in post-merge
context, required approval and hidden Git hook behavior, then passed after fixes.
A test harness mistake choosing a basetemp with a missing parent produced150
setup errors in259 tests. That JUnit is retained unchanged, not counted as
acceptance. After creating only the owned worktree's scratch parent, all259
passed with a new artifact name.

Runtime evidence directory:
`docs/project/runtime/fr06-recurring-task-health/interactive-integration-20261001T163237396620Z-fc60d209/`

- `source-integration-final-repaired-lab.xml`:
  `14638a4c3f51ea4f0cfd9adf352d8f70e875c4ce9bd98bc1d0ebf36e5d255305`
- `source-integration-negative-before.xml`:
  `6d427e23657c039ce73c5199c16c400b242cbf3c9a0254f608c7f6b62a2425e2`
- `source-integration-final.xml` (RETAINED harness failure):
  `7e2e78a477cab1d2236ccb159e37f5ac841a6a72fcd59e3f1e7139f1d0c1ccc2`

## Explicit unresolved boundary — no self-authorization

Native execution refuses an uninstalled operator, a dirty source, absent or
mismatched root-owned enrollment, mismatched installed launcher/code bytes, and
absence of a tracked, independently accepted ingress-enrollment verifier.
`fr06_execution_enrollment.py::verify_installed_routes` is a REQUIRED external
bootstrap verifier interface; its implementation/acceptance is NOT supplied or
claimed by this commit. An enrollment JSON or its digest alone does not prove
actual primary/watchdog/interactive routing or reconcile old uncertain effects.
No installer, issuer, fallback that returns true, uncertain-intent resolver or
force option is supplied. Test fixture enrollment cannot authorize production.

The circular bootstrap must be resolved through the existing authorized protected
source-review/installation path, not by letting the unreviewed guard authorize
its own PR merge. Previous platform refusals remain unresolved and were not
replayed through this candidate. Both live executor ingress and prior unknown
shared effects still need actual, reviewed acceptance. Thus this receipt does
NOT declare the shared-execution blocker solved on production.

C5D legacy stop-receipt adaptation and composite drain proof, host-state writer/
underlay integration, C5E activation/boot and C6 reboot/recovery remain separate
unaccepted requirements. The preserved sensitive incident file was not read,
printed, copied or sanitized. Credential rotation and misuse review remain
unverified; nothing here is incident closure. FR-06 remains in_progress and
FR-07's historical accepted closure must be preserved.
