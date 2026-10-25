# FR09 — actual validated provider-model capacity boundary

**Date:** 2026-10-25 UTC. Project: **AIONEX AIOS only** (`/opt/AIOS`).
**Source snapshot:** `FR09-20261025-PROVIDER-MODEL-CAPACITY-READONLY-V2-HOLD.json`
**Snapshot SHA-256:** `415aaae17ce33fde514eaff07fadcb2c524e41cbc340b0882696fb15ea7fc76d`

## Read-only current configuration

The query used the production runtime's **existing** `DurableProjectAIResolver._parse_model` parser. It did **not** read provider credentials, emit provider IDs or customer data, make a paid inference request, edit the live PostgreSQL database, or modify containers.

At capture time, the system had **16 configured provider rows**, of which **14 were connected and enabled**. Only **5 model validation entries**, covering the provider types **OpenAI (3), DeepSeek (1), and Mistral (1)**, carried fresh, parser-accepted, model-specific evidence. All five are under **one provider-owning organization**. **10 connected provider rows had no model validation evidence**, and one Ollama entry had stale validation evidence. The parser's acceptance does not independently prove paid vendor quota or tenant permission.

Assuming every fresh model's internal policy request/minute cap were independent — an *optimistic upper bound* — these five entries sum to **360 model requests/minute**. This is not observed model throughput, does not show provider account RPM quotas, and is not license to use one organization's credentials for another tenant.

| Full 15-minute model work | Model calls |
|---|---:|
| Minimum target | **15,000** |
| Required rate | **1,000/minute** |
| Maximum implied by existing validated per-model policy caps | **5,400** |
| Minimum model-call shortfall under those optimistic assumptions | **9,600** |
| Additional confirmed request rate needed | **640/minute** |

Evidence TTL at capture was under 6 hours for the earliest-expiring entry. The existing validation refresh must prove it remains fresh before actual use; silently extending or backdating validation is forbidden.

## Additional production gates

1. **Model-capable hardware or approved vendor fleet:** prove rate and concurrency with *genuine generated output tokens*, rather than deterministic synthetic completions. The separate 24-core CPU Gemma3:4b test peaked at **2.70217 calls/sec for short five-token generations**, versus **16.67 calls/sec minimum** for the basic 15,000-call/900-sec target. This does **not** determine an exact GPU count or price for real prompts.
2. **Per-tenant provider authority:** verify the organization-owned route policy, explicit allowed models, fresh evidence, local privacy restrictions, shared rate/circuit limits, and an approved cost/budget. Do **not** assume 100 synthetic tenants have access to the one current provider-owning organization.
3. **End-to-end proof:** account for **15,000 genuine model-backed ProjectExecutionWorker terminal executions** with persisted per-job prompt/response proof hashes and token counts, no duplicate terminals or tenant leaks, sustained full 5,000-active-user mixed workload, ordinary-read P95 <=500ms, enqueue P95 <=1,000ms, unexpected errors <=0.5%, and no lost jobs.
4. **Natural FR25 stability:** an intact **72-hour post-deploy release generation** is still needed. Preserve all historical G6 anomalies; never backfill missing hours, reset evidence merely to claim GO, or credit pre-deploy samples to a new deployment.

This policy inventory is a **read-only preflight**, not an authorization to increase external API spend or turn on a new GPU server. Commercial quotas/charges cannot be guessed from the internally configured limits.

The accompanying `scripts/capacity/fr09_provider_capacity_evidence.py` tool verifies the *internal consistency* of the sanitized evidence and fails closed on missing/wrong evidence, altered costs or quotas, false claims of production mutation or deployment, or an incorrectly asserted final release. It does not independently reproduce provider API network calls or attest actual vendor quotas.

**Release verdict: HOLD — missing real model fleet throughput, integrated accepted workload, approved quotas/budgets, and 72 natural hours.**
