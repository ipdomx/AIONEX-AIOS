# Phase 36C: bounded real local Ollama CPU performance and durable routing

Date 2026-10-27 UTC. Source base d6974872c7fc29003a3201fcba351d12ddfd5374. AIOS only. SOURCE CANDIDATE, no production image replacement.

## Actual incident and corrective measure

Gemma3:4b local model previously did not finish large structured-generation output within the accepted bounded timeframe despite healthy Ollama. Host is AMD EPYC; production Ollama Docker container is limited to 6 CPU cores. One synthetic strict compact project specification completed with num_thread=6: 232 real generated tokens in 12.55 seconds, total cold-load request 23.31 seconds. The strict reviewed model product JSON was accepted with 4 features and 1 record entity. The model raw text and synthetic prompt were deleted after recording the SHA256 and usage metrics.

Project AI-only code now configures num_thread=6 by default, permits explicit bounded PROJECT_AI_OLLAMA_THREADS from 1 to 8 and refuses invalid settings before network. Coder Ollama JSON output requests have 4096 context and deterministic structured format. Planner, researcher and reviewer in the validated local AI route use a non-tool bounded 192-token output adapter rather than the generic longer conversation adapter. Non-Ollama paid provider paths, the generic AI service and existing customer routing admission/consent remain unchanged.

## Test evidence

19 disconnected synthetic request-contract tests passed for both new and existing Ollama/OpenAI coder adapters, token bounds, six thread defaults/overrides, and no-network on invalid settings. Two further real synthetic-tenant PostgreSQL runtime invoker tests passed, proving planner and coder dispatch through the scoped new entrypoints, not the old general provider path. No billable APIs, customer prompts or real production worker executions occurred.

## Remaining honest boundaries

A full four-role customer application with actual Gemma invocations, production concurrency, and 5000 authenticated users/15000 durable AI tasks remain unverified. The offline strict product spec is one tested synthetic model prompt, not a generalized quality or throughput guarantee. No 72-hour full go-live approval is claimed. Independent physical cold-host disaster rehearsal remains Owner-deferred postlaunch without weakening backups.

Evidence /mnt/aionex/fr09-isolated-lab-20261011/fr08-ollama-sixthread-live-invoker-20261027/FR08-OLLAMA6-ROUTER-EVIDENCE.json
Evidence SHA256: 266219212787680b1e7e0bdcc04ee09d9703646d51345cff827fbe65e47f54b0
Original real Gemma spec SHA256: ef610758accea417319c913fd206461ab47ddbb0dc1ac3852860a98708d8ee27
Local adapter contract SHA256: 92bdedc416e801934f335e0d73fd048d95935fad8e6fec8414eef09cf6335358
Synthetic PostgreSQL route-test SHA256: f28daa43109ec1112aa64a5200765da00b62490bd167435cd847f38391037a00
