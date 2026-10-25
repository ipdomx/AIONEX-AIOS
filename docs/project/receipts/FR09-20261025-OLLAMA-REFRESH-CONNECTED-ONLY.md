# FR09 — Repair local Ollama launch-model evidence refresh

Date: 2026-10-25 UTC. Scope: **AIONEX AIOS** only. This is **source-only**, not a production rollout or final-launch admission.

## Diagnosed production condition

The production `operations-observer` was already running `refresh_launch_model_evidence` on the configured schedule. Its four most recent audited refresh cycles all reported `ollama:provider-record-count-2`. A read-only query verified **two Ollama provider rows** in the configured platform provider organization: **one `connected`**, **one `configured`**. The active local Ollama service itself was healthy and was able to complete genuine Gemma3:4b model generations in separate tests, but its **validated-model evidence was stale** because the refresh counted both database rows.

This is not evidence that the configured sibling grants runtime provider authority. It is an ambiguity in **refresh candidate selection**. The durable live provider resolver itself already restricts routing to connected, enabled providers.

## Narrow, fail-closed correction

Update `app.services.project_ai_model_refresh.refresh_launch_model_evidence` to select only connected providers and exclude disabled provider records before checking that **exactly one** eligible row remains for each launch provider type.

The source retains all other safety boundaries: never choose the first of multiple connected, enabled records; never promote a configured/disconnected record; no credential bypass, fabricated model evidence, relaxed expiry, provider charge or false success. **Two live eligible Ollama records still fail closed.**

## Verified in disposable PostgreSQL 16

After applying the full Alembic migration chain inside an independent network-isolated PostgreSQL 16 lab:

- **19/19 targeted model refresh, scheduling, provider evidence and policy tests passed**.
- New integration scenarios verified that one connected Ollama provider refreshes successfully despite `configured` and disabled sibling records; two connected enabled records fail closed; and a configured-only record cannot be promoted.
- Ruff and mypy succeeded for modified code. The lab database and containers were deleted.
- The production Observer/Backend images, PostgreSQL data, and pre-existing G6/NS12 natural stability records were not changed.

## Full capacity remains HOLD

Refreshing a valid Ollama model entry would contribute its configured **120 requests/minute internal policy cap** to the current **360 requests/minute optimistic upper bound** of other fresh entries, *if* the new evidence is current and per-tenant route policy authorizes it. Even then, **480 policy RPM** is still below the minimum **1,000 generated model calls per minute**, and it is not proof of CPU throughput, account quota, provider billing or permitted inter-tenant credential sharing.

Deployment would form a new production release generation, and requires post-deploy natural 72-hour monitoring. Do not restart production workers or backdate model validation merely to meet a clock goal.

**Status: SOURCE FIX VERIFIED; PRODUCTION NOT DEPLOYED; FINAL RELEASE HOLD.**
