# FR09 genuine model invocation + durable project-worker pilot

**Date:** 2026-10-25 UTC
**Source baseline:** `8798b3a384955d374b778a9f46f1866e63c6b91b` (post-PR #983)
**Verdict:** **PILOT VERIFIED; FINAL_RELEASE HOLD.**

## What genuinely ran

Using the existing production `app.services.project_execution_worker.ProjectExecutionWorker` class inside a **disposable, independent network-isolated Docker/PostgreSQL 16 environment**, the pilot:

- Created **4 synthetic tenant organizations**, **16 synthetic users and 16 distinct projects**.
- Queued **16 real durable ProjectExecution records**.
- Claimed and completed all 16 through the worker's real lease, fencing and terminal state machine, including 16 correlated claim audit events and 16 correlated completion audit events.
- Replaced the normal planning runner with an **explicitly injected pilot-only adapter** that called an isolated CPU-hosted **Ollama `gemma3:4b`** model for each job and validated that an actual model response and positive generated-token count were returned.
- Persisted **2,018 input tokens and 48 generated output tokens** across the 16 job rows. Each row includes an output digest, prompt digest, tenant, job and project reference, one claim audit, one completion audit, and a verified released lease.
- Completed the worker phase in **21.39 seconds** in this **small local pilot**. It does **not** establish 15,000 model calls or provider-capacity acceptance.

Original sealed evidence was copied byte-for-byte to
`FR09-20261025-16-REAL-MODEL-WORKER-PER-JOB-PROOF.json`.

Raw evidence SHA-256:
`dcab6e3ba4b158a4ecd357f0dd548f97f963604cbff19c789d1673667c812b8e`

The `scripts/capacity/fr09_real_model_worker_evidence.py` checker verifies every row, distinct execution/project identity, organization consistency recorded during live SQL auditing, hash-chain digest, real-model token accounting, fencing, and each audit correlation. It fails closed on deterministic fake-provider jobs, missing model tokens, duplicate jobs and projects, repeated or missing audit events, suspended/mismatched ownership assertions, and false launch-status claims.

**Important independent-verification limit:** The checker validates the *stored manifest's internal consistency* and requires the pilot to retain its original no-GO status. A valid-looking output digest alone is **not independent proof that the actual provider was contacted**. The original isolated runner observed and verified real model responses; future full acceptance needs independently attestable provider call logs or equivalent server-side instrumentation.

## Capacity boundary

Separate bounded real model samples established 2 earlier + 8 current production-local + 73 isolated + 16 worker-integrated = **99** genuine model invocations in **different non-overlapping tests**, **not** one coherent 99-job production profile.

For the isolated `gemma3:4b` 24-CPU pilot, the highest short-prompt rate measured was **2.70217 calls/second** with 8 client requests in flight. A target of **15,000 genuine calls in 900 seconds** requires **16.667 calls/second**, a 6.17x shortfall relative to that one bounded measurement. Real prompts, model quality, provider quotas, budget/cost, network routing, and approvals can change that figure. Do not infer a precise GPU count from this CPU test.

The separately verified 5,000-user/100-tenant/225,000-HTTP-200 15-minute profile covered *paced read requests* only. It did not load the AI model execution path or demonstrate 5,000 simultaneous outstanding requests. The 15,000 prior provider-neutral completed durable jobs are **not** model inferences.

## Full release remains blocked

Missing: a cost-bounded, authorized GPU/provider inference fleet; 15,000 attributable real-model-backed durable jobs with output tokens and tenant isolation **under the integrated accepted workload**; true P95 service/queue and job accounting at full capacity; and 72 unbroken natural post-deployment production stability hours. All governance layers were deliberately **not** passed in this pilot, and no job was marked finally approved.

No production images, customer database, Cloudflare Access, credentials, billing, or provider resources were changed for this evidence batch.
