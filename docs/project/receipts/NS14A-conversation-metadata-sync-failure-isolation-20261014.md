# NS14A — Do not clear durable conversation transport errors during unrelated metadata refresh

**AIONEX AIOS only.** Protected-main base `1f7e6a17281cb9da9d31286495b7a63959a1344e` on NEW `nc-ph-4354`, 2026-10-14.

## Specific source defect

`vip-frontend/src/components/pages/conversations-client.tsx` previously executed `setSyncFailures(0)` whenever `load()` successfully refreshed **project/conversation list, policy and agent metadata**. Those calls do **not** verify that the selected conversation's durable **message-history polling** has recovered. Clearing the transport-warning counter on an unrelated success is a genuine state ownership error, especially when an auth/session/metadata re-fetch races with transport loss.

The patch removes exactly that reset while keeping both appropriate reset locations unchanged:
- A successful **selected conversation's** `conversationApi.history(selected)` + policy poll resets failures and hides reconnection warnings only after validated history.
- Actual conversation selection changes or logout invalidate the old history and clear its failure state.
- Failed history reads still increment `syncFailures`; no message POST is replayed by the polling effect.

No billing, auth policy, API contract, worker, rollback, provider secret, or existing browser-test assertions were changed.

## Red/green verification

- Added new source-boundary test `tests/test_ns14a_metadata_refresh_sync_failures.py`: **1 fail / 2 pass on unchanged protected main**; after the isolated patch **3/3 PASS**.
- Real Node 24.20.0 isolated `npm ci` from the exact frontend lockfile PASS; `npm run type-check` PASS, `npm run lint` PASS, and full `NEXT_PUBLIC_API_URL=https://api.vip-e.net/api/v1` production **Next build PASS**. Source and Python checksums retained locally.
- No production code/image deployed for this patch.

## Critical deployment evidence / limits

Before this patch a production-site switch to the *previous* protected image `sha256:0c1e0fc1905b8ccff59fc9907f57948706defe7b3009660677f5a14fa352367e` reached Healthy and matched all other 35 running services but only **5 of 6 original Playwright NS14A tests** succeeded on `https://ai.vip-e.net` with one worker, zero retries. The original six had passed 6/6 inside the isolated lab. Automated, verified Portal-only **rollback to the original image** completed; no such client release accepted. Protected issue #884 contains the operational receipt. This was not caused by an old image being served: public and container asset fingerprints matched.

Additional controlled diagnostics showed a previous deployed client could revert to its generic loading state during repeated aborted history reads. Production API preflight authorizes synthetic valid UUID paths, whereas a formerly used invalid test-only conversation string returns 404; a private cross-origin canary still failed pre-authorization, so **neither an invalid fixture nor the one-line patch is claimed to explain all public test failures**.

**Acceptance rule:** this source correction must pass exact-head protected CI and a separately reviewed deployment with unchanged original six Playwright assertions **6/6 on the live public portal**, then real terminal-event/replay/reload evidence. Do not replay the previously rolled-back unchanged image or bypass any guard. Full NS14A, FR06/FR08E/FR24, real FR09 5000-user workload, physical OLD disk archive and final release remain **NO-GO**.
