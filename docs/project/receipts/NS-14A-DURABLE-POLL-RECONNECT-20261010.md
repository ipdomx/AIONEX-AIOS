# NS-14A — Preserve durable conversation status through polling re-subscriptions (2026-10-10)

**Status: source proposal only, not production deployed or runtime acceptance.**

## Trigger and evidence

The existing required browser test "NS-14A repeated transport failures recover the same durable terminal result without POST replay" failed in PR #892 (head `3590fd124ed0da189acf6eb1f720c77edd417de3`), run `38088693270`, job `114320501027`, despite 24 other browser tests passing. It observed >=2 intentionally aborted history GETs, yet the reconnecting banner was not visible within 10 seconds on either attempt. The PR #892 changes do not touch the frontend or this test. Network logs included unrelated proxy DNS EAI_AGAIN messages; cause remains under investigation rather than assumed.

## Specific defensive source change

The selected-conversation polling React effect previously called `setHistory(null)` on **every effect re-subscription**, including an unchanged selected conversation. That transient clear can hide the saved pending message and thus suppress the reconnecting banner precisely during transport disruptions. Change the effect to invalidate cached history only if the selected conversation actually changes or auth is lost. On a same-selected re-subscription it retains the last durable observation while the poll continues read-only and reports failures; the existing protected reconnecting tests must still pass. Never re-submit a POST. Authentication loss must still clear cached private message content.

This proposal is **not proof that the observed browser test failure is fixed** until exact-head browser CI completes successfully; do not weaken/retry-loop/mark the prior red run green. User data, actual provider calls, storage, Docker, Cloudflare and NEW production are unchanged.

## Release boundary

Keep PR #892 red and unmerged until its required exact-head checks are green on a fresh reviewed head. Only accept this distinct NS-14A source change after protected exact-head tests succeed; then coordinate with the existing FR-09G worker rather than editing their branch or bypassing serialized release governance. No production deployment is performed by this PR.
