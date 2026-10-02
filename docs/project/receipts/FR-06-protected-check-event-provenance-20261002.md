# FR-06: bind source acceptance to original GitHub workflow events

Base: `ce0ddc43ca7e5f1723736b03cd1856c5fc25f4c9`, PR838. This corrects the source gate, not the workflow configuration or the independent installation trust policy.

## Reproduced defect

The old `required_checks` accepted a matching successful name/app/SHA without checking its original Actions run. Four baseline regressions reproduced acceptance of workflow_dispatch and schedule jobs for both source_merge and source_sync. Such jobs can be genuine passing diagnostics without satisfying the protected pull-request policy.

GitHub documents the distinction in https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks#checks-from-some-workflow-jobs-are-not-evaluated . Job and run metadata are obtained using the documented fixed GET endpoints, never from a details_url: https://docs.github.com/en/rest/actions/workflow-jobs#get-a-job-for-a-workflow-run .

## Implemented boundary

Both source merge/sync and the native initial-install source reader now require original workflow evidence in addition to unchanged strict app-bound status checks. For each required github-actions check, the collector reads its fixed job endpoint and deduplicates the corresponding run GET. The validator binds check/job/run IDs, check-suite ID, run attempt, successful completion, exact head SHA and both repository identities. Pull-request acceptance requires the matching PR number, head, base branch and base SHA. Installed main acceptance requires a push to main. Missing or mismatched provenance fails closed; there is no legacy status-only fallback.

Only the two events used by this project's source protocol are supported. GitHub supports additional event types generally; this change does not claim otherwise or enable them. External GitHub App checks retain their own app-bound status semantics and are not given fictitious Actions runs. The status-only parsing helper is internal and is no longer an execution acceptance entrypoint.

The new checks do not authorize any merge, reconcile old effects, create a signer or permit, install or enroll an executor, or modify production. The prior platform-refused PR838 integration was not retried. No workflows, branch rules, required thresholds or application services were changed.

## Evidence and limits

Run: `docs/project/runtime/fr06-recurring-task-health/interactive-check-provenance-20261002T151955415363Z-19d46176/`.

`provenance-before.xml` retains four baseline failures. The first combined after-run retained one old fixture failure because a newly required context had a status but no job/run proof; the fixture was completed, without weakening production validation. Directed tests include no-effect/no-intent assertions for all invalid event types, job/run identity and attempt changes, API failures, wrong/duplicate PR links, missing/extra evidence and the actual native reader wiring. External transport responses are explicit fixtures in those tests; file locks and isolated Git remain real where exercised.

An actual read-only metadata comparison separately accepted the eleven eligible automatic PR838 checks on ce0ddc43 and rejected the earlier all-green manual workflow_dispatch diagnostics on04f6c273. The result is retained in live-event-provenance-observation.json. That observation concerns those existing source heads; it is not protected CI for this new patch or a deployment grant.

The complete unprivileged source export and full-suite XML/result are retained in this run directory. Read their actual exit status, hashes and counts rather than inferring completion from a started process. All directed counts overlap the full suite. FR06/C5D/C5E/C6 and the incident remain open; FR07 remains preserved.
