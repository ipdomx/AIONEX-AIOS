# FR09 local model inference: independent proof (2026-10-25)

The completed 15,000 durable worker tasks on 2026-10-24 are a separate gate
from 15,000 actual LLM-generated responses. Local inference proof needs
an installed model with digest, per-request nonzero output token counts,
completed (not truncated) generation, and validated model answers.
Do not infer model execution from provider-neutral worker completion.

The new scripts/capacity/fr09_local_inference.py sends private synthetic
classification prompts to local Ollama only, and emits per-request hashes
and an overall hash chain. It cannot contact an external paid model.
Production-network sampling is capped at 16 calls and is explicitly
NOT full FR09 evidence. High-volume execution requires a dedicated
isolated lab with verified receipt, loopback-only model access and no
production/customer database mount or paid-provider access.

Command for a bounded sample from the actual Ollama-connected backend:

  docker exec -i web-dashboard-backend-1 python - --count 4 < scripts/capacity/fr09_local_inference.py

Do not execute 15,000 inferences against the production network.
The full release still requires 5,000 concurrent authenticated active
users, 15,000 durable worker jobs, full mixed 15-minute workload,
P95 ordinary read at most 500ms, no tenant leaks, and 72h natural stability.

Actual bounded sample (2026-10-25 UTC, private Ollama network): 2/2 independent model responses validated, 6 generated tokens, 21.610s wall clock, 21,592.27ms p95. Sample is NOT 15,000 real inferences, NOT durable worker proof, NOT FR09/FR25 GO.
