# FR-06: repair nonroot CI enrollment fixture without relaxing production

Base: PR #835 `0d7781c436f18963e474bb7570dbd8814006d257`.
Status: source review candidate; not an installation, enrollment, activation or deployment.

## Reproduced current-head failure

GitHub Actions core job `110544047544` completed with 3901 passed and three
failures. All three failed at the production root-installation predicate, before
native evidence/probe plumbing. The earlier root-only local pass concealed this
fixture assumption. Running the original enrollment module as Unix UID 65534
reproduced exactly three failures and 108 passes.

## Narrow change

The two original installation predicates are moved unchanged into
`_require_installed_context`. The production entry invokes it before any command
or receipt read. It is not a configuration option, environment switch or CLI flag.
The native test fixture explicitly substitutes only this installation boundary;
it does not change `os.geteuid`, file ownership enforcement, subprocess identity,
real kernel flock behavior or production authorization.

Eight new independent tests verify nonroot rejection, alternative source/guard
path rejection, uninstalled-module rejection before I/O, and that the modeled
boundary alone returns no activation authority. The existing bootstrap-mutation
test now requires its specific error, rather than passing on an unrelated early
permission denial. No skips, xfails, workflow changes, CI privilege escalation,
threshold reduction or production flags were added.

AST comparison with the base proved the original two production predicates
identical. Predicate SHA-256:
`958959ace906e377b9ba4527e8590016ef48d09f62481ccf10ee5198d314868f`.

## Retained verification

Evidence root on the server:
`docs/project/runtime/fr06-recurring-task-health/interactive-ci-20261001T193652011121Z-62434ee1/`.

- `nonroot-before.txt`: three original failures, 108 passes.
- `selected-root.txt`: 515 passed.
- `selected-nonroot.txt`: 515 passed.
- `guard-predicate-proof.json`: unchanged production predicates.
- `nonroot-full-suite.xml`: first full nonroot laboratory attempt, 3903 passed,
  nine file-permission failures, zero errors/skips. That checkout was root-owned;
  the nine failures were unrelated tests writing local scratch/bytecode/data.
  They are retained and are not relabeled as a passing suite.
- `owned-checkout.json`: a separate UID-65534-owned export, excluding untracked
  production/runtime files; all 2686 relevant source/test files matched the
  candidate worktree before the complete-suite run.

- `owned-full-suite.xml`: second laboratory attempt, 3911 passed and one
  fixture-location failure: a child deliberately scanned /tmp while its source
  checkout itself was in /tmp, so its current working directory was correctly
  reported. No production code or scanner assertion was relaxed.
- `final-owned-checkout.json`: identical source export owned by UID 65534 under
  an isolated /opt/AIOS-worktrees directory, matching the non-/tmp CI profile.
- `final-lab-targeted.txt`: 178 passed, including the actual mmap/proc regression.
- `final-full-suite.xml` and `final-full-result.json`: **3912 passed, zero
  failures, zero errors, zero skips**, exit code 0, actual unprivileged process.
  JUnit SHA-256: `4e94a475c361d05884961860baf9f8dcdf1c9e406fcf4657c0702bb9e6c77939`.
  Finished at `2026-10-01T19:51:27.097730+00:00`.

No protected CI success is inferred from local execution. Prior laboratory
failures remain retained with their real outcomes and are not counted as passes.

## Operational limits

This change does not settle historical run effects, establish common executor
enrollment, repair missing C5D legacy provenance, or activate C5D/C5E/C6. The
historical C5D adapter is not changed by this patch. Neither raw production
Docker environment data nor the quarantined incident file was read or copied.
A source review update is not main acceptance, source synchronization or a
production release. FR-06 remains open; FR-07 is preserved as previously closed.
