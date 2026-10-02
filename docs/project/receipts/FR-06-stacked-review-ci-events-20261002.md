# FR-06: run existing required checks for the stacked source-review queue

Base: `04f6c273d2ded285a2290fb9b09fbdf642690247` (PR838).

## Actual blocker and correction

PR838 targets the canonical review branch `fix/fr06-source-rollup-20261001T1126`, not main. The existing Final Validation, CodeQL and Backend SBOM workflows restricted pull_request base branches to main. As a result only browser and repository-hygiene checks ran automatically on the child PR. This change adds `fix/fr06-source-rollup-*` to those three pull_request branch lists. Push remains main-only; the existing jobs, action pins, permissions, scripts, security thresholds, manual dispatch entry and schedules are byte-for-byte unchanged outside the three trigger lines.

This EXPANDS testing. It does not merge PR838, change its base or head repository, change branch protection, create an approval, provision trust, or deploy to production. The previously refused merge is not retried by this change. Automatic pull_request checks must actually execute on the new commit before acceptance is reported.

## Manual diagnostics are NOT protected merge acceptance

Three existing workflows were manually dispatched on parent04f6c273 before this correction: Final Validation37015537873, CodeQL37015673703 and Backend image security37015717012. Their results are useful source-test evidence only. GitHub documents that workflow_dispatch job checks do not satisfy a required branch-ruleset status check, even when the head SHA matches. Do not combine manual and automatic checks into a protected-acceptance claim.

Primary reference: https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks#checks-from-some-workflow-jobs-are-not-evaluated

## Reproduction and evidence

Twelve standard-library configuration regressions cover exact additive base filters, preserved main-only pushes, admitted main/canonical review bases, rejected unrelated bases and retention of the read-only/manual workflow interface. Before correction six failed and six passed. Retain the before XML; do not relabel those failures. Validation of the corrected source and real GitHub event provenance is recorded separately after execution.

A structural and byte comparison of the three workflows verifies that ONLY the pull_request base lists changed. Evidence directory: `docs/project/runtime/fr06-recurring-task-health/interactive-current-head-ci-20261002T135144787439Z-6b7f3c15/`.

The initial combined production-read request in this interaction was blocked before execution; it was not retried or used to assert fresh production health/source. Subsequent actions are source review, isolated configuration testing and their own reporting only. No production source sync, MCP restart, key/permit issuance, installation, enrollment, historical-effect reconciliation, provider/service/swap/tmp/reboot action occurs. FR06 remains in progress and FR07 is preserved.

## Local correction verification

After the three additive trigger changes all12 new cases passed. The selected suite including existing Ruff, portal-origin and security-observability workflow contracts passed24/24; these overlap the12 new cases. PHASE36_REPORTING_OK changed_paths=5. No new full local-suite result is claimed: complete validation is delegated to the actual automatic pull_request runs on the subsequently published commit.
