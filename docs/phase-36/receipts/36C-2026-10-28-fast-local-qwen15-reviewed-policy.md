# Phase36C actual CPU-local Qwen 1.5B model policy and Free route

Date: 2026-10-28 UTC. Scope: AIONEX AIOS only, parent protected main 9b705c2309dce371014a6598c89acb033701d7bd.

## Functional improvement

- Adds specifically reviewed locally served qwen2.5:1.5b to the launch allowlist, retaining Gemma as a separately validated manual rollback option.
- The default Free Project AI route selects the responsive local model and still requires fresh provider inventory, tenant/user rights and zero external spend.
- Conservative internal limits: 8192-token model context, 1 concurrent request, 24 requests/minute, 120-second lease, zero provider tokens billed externally. No model tool execution, audio or vision asserted.
- Existing paid models and credit policies are unchanged. Stored Owner plan policy overrides remain independently controlled and require audited migration.

## Actual verified CPU model and generated product

- Official Ollama qwen2.5:1.5b model was pulled and reported ID 65ec06548149. The installed Gemma3:4B rollback model remains.
- Real Ollama returned 181 strict JSON tokens in 4.57 seconds generation, 7.43 seconds total. The exact compact product model output passed strict AIONEX input validation.
- All four real local role prompts (planner, researcher, coder and reviewer) were invoked, totaling 17.76 seconds. Each model response has a retained SHA-256 provenance digest; no paid provider or customer information used.
- The reviewed AIONEX compiler produced 32 actual project files, ran source tests and archive/rollback checks, and recorded all six engineering governance departments in approximately 0.62s.
- A real localhost Python/SQLite server then passed 8 HTTP CRUD/security tests: health, browser HTML, record creation, durable read, invalid body rejection, deletion and security headers. No public port or production database writes.
- Actual final project approval remains withheld because independent external research and Owner sign-off were not verified. No such evidence was fabricated.

## Production controls and remaining acceptance

- Local validated model evidence is refreshed from actual Ollama /api/tags and expires after six hours in accordance with the existing fail-closed TTL.
- Existing Owner Free-policy override must be changed via the audited policy service after CI and source rollout.
- Real capacity 5000 authenticated concurrent users, 15000 AI-backed jobs and natural 72h remain unaccepted, as does overall go-live.
- Only physically separate cold-host disaster recovery was deferred postlaunch by explicit Owner decision.

## Evidence checksums

- Real Qwen schema admission: 47e99156729887b2232459ddafb863150944467289a6477db84c3a3b6eee7d7d
- Four actual model calls / reviewed compilation: 9f3578ac0c0bec05659c46ec824769e62c728c270af4358e061452a3ac98d5f4
- Real SQLite/HTTP generated app acceptance: 2377866e56675bfa8e624c220a60f7cff4600201dde8012252cf0841a8934470

This is an evidence-backed source and local execution milestone, not a full release certificate.
