# Identity media: invalid successful creation receipts require review

Scope: AIONEX AIOS only. Source base `b76fdafd5bae0591b5493113ee00d149b73fb8fd`.

The Replicate adapter previously classified malformed JSON or an invalid prediction
payload after HTTP 200/201 creation as a definitive `provider_response_invalid`
failure. The provider may already have accepted the POST. Both model and pinned
creation now preserve that code while setting `ambiguous_submission=True` and
recording the HTTP status. The worker's existing needs-review path is therefore
used, without adding retries or changing polling, authorization or cost limits.

Verification on NEW nc-ph-4354 in a separate worktree:
- New regression suite against the unmodified source: 20 failed / 43 passed.
- Same suite after the two guarded response-handling changes: 63 passed.
- Existing identity policy tests plus the regression suite: 68 passed.
- All transport tests use httpx.MockTransport; no provider requests or database
  writes are made by these tests. Both POST paths are asserted to issue one request.
- Existing 4xx, 5xx, transport failures, successful receipts and GET polling remain
  covered. No existing test was weakened.

Evidence: `/var/lib/aionex-migration/launch-continuation-20261021T1755Z/`.
The separate bounded GET-only provider history audit did not identify an unmatched
provider ID for the seven historical needs-review records; its one candidate was
already linked to a completed local execution. This source change does not resolve
those records and is not claimed to be their historical root cause.

Protected CI, merge and deployment must be verified separately. No production
worker restart, requeue, paid model invocation, full recovery acceptance, capacity
acceptance, or final-release acceptance is asserted by this receipt.
