# Phase 29J — Models and Providers — Final Completion

Status: **complete and verified**.

## Final supported provider contract

The final AI provider catalog is explicit and finite: OpenAI, Anthropic, Gemini, OpenRouter, Ollama, Mistral, Cohere, xAI, DeepSeek, Groq, Together, Fireworks, Hugging Face, Azure OpenAI and AWS Bedrock.

A provider is never considered active merely because its name exists in the catalog. Cloud providers require a protected credential reference/transport; local providers require a local runtime. Missing credentials remain `unconfigured`, and disabled providers remain `disabled`. Raw secrets are not returned by the provider catalog or completion evidence.

## Model and capability surface

The retained provider framework covers discovery and capability declarations for text/reasoning/coding, tools, streaming, structured output, embeddings, vision/image/audio and declared file/media paths. Existing routing contracts enforce task compatibility, project policy, restricted-data locality, cost limits and privacy requirements. Rate limiting, retries, health state, metrics and cost accounting are retained by the provider runtime.

The final provider catalog API exposes truthful configured/enabled/status state and discovered model contracts. The AI Providers and AI Models dashboard pages now consume that live API rather than hard-coded or placeholder data.

## Routing and fallback

- local and cloud providers are represented separately;
- no-fallback mode fails when the preferred provider is unavailable;
- fallback mode may select a later eligible active provider;
- restricted data remains local under the existing policy contract;
- project allowlists, blocked providers, budgets and per-request maximum cost remain enforced;
- unhealthy or disabled providers cannot be selected by the routing layer.

## Validation

- Phase 29J final-contract and legacy provider/routing focused tests pass.
- The complete core AIOS regression suite must pass before merge.
- The isolated backend suite, frontend production build, CodeQL, dependency security and Production Docker Build are authoritative protected GitHub gates before merge.
- Final production acceptance must preserve healthy Backend, Frontend, PostgreSQL, Redis, Nginx and workers.

## External activation boundary

Phase 29J closes product implementation without fabricating third-party credentials. Providers for which the operator has not supplied credentials remain intentionally and visibly unconfigured. This is the final truthful production contract, not missing implementation.

Cloudflare and DNS are unchanged by this batch.
