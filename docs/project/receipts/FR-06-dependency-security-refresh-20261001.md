# FR-06 — Independent dependency security refresh, 2026-10-01

## Scope and source identity

This is an isolated, unshared source change, based on canonical PR #835 head
`87d52daee928e4faa9c20c360664517c8321c748` in
`/opt/AIOS-worktrees/fr06-dependencies-20261001T172610`.
The production source was observed at
`7779f740a81d4fae2167c8441218b69e54cf56f5`, with the existing untracked `$dir/`
preserved. No branch push, pull request, merge, source synchronization, deployment,
service change, provider request, maintenance transition or bootstrap enrollment
was performed. This change does not modify or approve the concurrent enrollment
audit or any previously refused operation.

## Source remediation

* TripoSR `requirements.txt` and `security-overrides.txt`: urllib3 2.7.0 -> 2.8.0,
  addressing the affected source pins for alerts #39/#40,
  GHSA-8988-9cw3-xx77 and GHSA-vxq7-64xx-v4gw.
* VIP frontend: exact override for @grpc/grpc-js 1.13.6, replacing locked 1.9.16,
  addressing the affected source instance for alert #43,
  GHSA-m9gg-hp2v-232j. Its new ordered-map dependency is retained in the npm lock.
* A real npm audit after the gRPC update found brace-expansion still vulnerable.
  Targeted lock updates retain each dependency's compatible major version:
  root 1.1.18 -> 1.1.21 and the TypeScript-estree nested instance 5.0.9 -> 5.0.12.
  These versions include the recursion and quadratic-expansion fixes described in
  GHSA-6j4f-fj2g-mc7p, GHSA-qhr7-859c-m2p7 and GHSA-q2hr-2g5m-vwhr.
* No other lock package changed. Firebase, Next, React and the existing Sharp
  override remain unchanged. Registry-generated integrity values are retained;
  install lifecycle scripts were disabled.

## Actually completed validation

Evidence directory:
`docs/project/runtime/fr06-recurring-task-health/interactive-dependencies-20261001T172610Z/`.

* Before the fix, the seven new source contracts had four expected failures and
  three passes (`dependency-before.xml`).
* After the first source fix, 27 selected tests passed (`dependency-after.xml`).
* On the final source, all 29 selected tests passed (`dependency-final.xml`):
  nine new source contracts plus existing Dependabot/frontend-group/hub contracts.
  These are not additive to the earlier 27 cases.
* The final installed Node dependencies passed three native tests
  (`node-behavior.txt`): disposable loopback-only gRPC unary exchange, normal brace
  expansion, and bounded 3200-level nesting against both patched brace instances.
  The local gRPC server and client were closed in a finally block.
* The isolated installed urllib3 2.8.0 passed four native tests
  (`urllib3-behavior-final.txt`): version, normal chunked parsing, oversized chunk
  line rejection, and proxy TLS-policy selection using a mocked TLS wrapper.
  The last case does not claim a real TLS handshake or certificate-chain test.
* The isolated Python 3.12 environment installed the official urllib3 wheel and
  passed pip check. This is not full TripoSR dependency resolution, its Python 3.11
  GPU image build, inference or runtime acceptance.
* Before the additional brace lock update, the frontend integrity check (105
  files, six locales), type-check, lint and production-mode build succeeded.
  That build generated 145 pages. This build is NOT final-lock acceptance.
* Final `npm ci --ignore-scripts` succeeded, installing the final lock's 493
  packages (`npm-ci-final.txt`).

## Preserved failures and incomplete validation

The first npm configuration attempt failed before lock generation because user
and global config pointed to the same null file. The lock was inspected before
correcting this isolated test setup. The first in-memory HTTP fixture omitted
its request method and caused two harness errors; the original failure remains
in `urllib3-behavior.txt`. Adding explicit GET fixed the fixture, not the library.
The first audit (`npm-audit.json`) reported one high vulnerable package,
brace-expansion; it must not be quoted as a final audit result.

A later grouped call requesting a final npm audit and repeat frontend checks/build
was blocked by the tool's safety gate before execution. Its final output files
were absent on a subsequent directory read. That call was not replayed through
another tool or route. Final audit and final-lock frontend build remain unverified;
there is NO claim of zero vulnerabilities. Resolve any refused execution through
the normal approval/security path, not an alternate executor.

## Gates retained

The existing primary task and watchdog remain enabled; scheduler timestamps are
not terminal receipts. Three observed scheduled runs (13:01, 13:58 and 16:01 UTC)
and the 15:30 watchdog lacked terminal files at the inspected time. No historical
run outcome or side effect was invented or reconciled by this source work.

PR #835 remains the canonical shared queue. Its existing eleven required checks
were successful, but this local bundle is not included in that checked head.
GitHub main is protected by ruleset 19771501, including strict current-head checks
and pull-request requirements; the legacy branch-protection endpoint's 404 is
not proof that the branch is unprotected.

All six observed high Dependabot alerts remain open on GitHub until reviewed
source is merged and rechecked. Trivy-related #48/#50/#51 were not remediated here.
The prior restricted credential-output incident remains unresolved: this work
neither reads the restricted raw artifact nor rotates credentials or resolves
usage review. Do not include that artifact in collectors.

Publishing or installing any source still requires independently accepted common
execution ownership, live source/security review, applicable protected checks and
reconciliation of uncertain earlier effects. This local change cannot authorize
its own publication. FR-06 remains in progress; C5D host-state migration, C5E
swap/tmp protection and C6 reboot/recovery acceptance are not closed.

## Reproducible test entrypoints

The source contracts are collected by normal root pytest:

```sh
python3 -m pytest -q tests/test_fr06_dependency_security_refresh.py tests/test_fr03_dependabot_scope.py tests/test_fr03e7_frontend_runtime_group.py tests/test_project_hub.py
```

The explicitly separate native labs require the patched dependencies in an
isolated environment. They perform no provider or production I/O:

```sh
node --test tests/security_labs/fr06_node_dependency_refresh.cjs
<isolated-urllib3-2.8.0-python> tests/security_labs/fr06_urllib3_refresh.py
```

Do not interpret these entrypoints or this receipt as permission to replay a
refused operation, modify an active worktree, or bypass protected review.
