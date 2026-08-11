# Phase 29J — Synthetic Provider Acceptance — 2026-08-11

Status: **implemented; network-free acceptance must pass before merge**.

This acceptance is intentionally synthetic. It does **not** claim third-party connectivity or
credential validity. It exercises the production request/response adapter paths without sending
traffic to any provider and without consuming paid tokens.

## Acceptance matrix

The general agent runtime covers OpenAI, Anthropic/Claude, Google Gemini, OpenRouter, Ollama,
Mistral, Cohere, xAI, DeepSeek, Groq, Together AI, Fireworks AI, Hugging Face, Azure OpenAI and
AWS Bedrock. The test replaces only the outbound HTTP boundary and then executes the real
`_execute_provider` production adapter, validating provider-specific payloads, response parsing,
usage accounting, latency, output requirements and secret non-disclosure.

Tripo3D and Meshy are explicitly excluded from the general chat runtime. Their health and
execution remain delegated to the dedicated 3D pipeline, and the general runtime now fails closed
if either provider is routed there accidentally.

## Release rule

Passing this suite means the internal provider contracts are synthetically exercised. It does not
mean every external provider is live. A provider may be called `connected` only after a separate
credentialed live acceptance against that provider succeeds and durable execution evidence is
recorded.
