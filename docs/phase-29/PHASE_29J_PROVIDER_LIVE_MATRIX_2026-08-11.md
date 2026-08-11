# Phase 29J — Credentialed Provider Live Matrix — 2026-08-11

Status: **partial external activation: OpenAI, Gemini and OpenRouter live-passed; direct Anthropic execution is billing-blocked.**

This record follows the network-free provider acceptance. It does not convert configured providers into `connected` unless a real credentialed execution succeeds. Provider secrets are not retained in this evidence.

## Live matrix

| Provider | Credential / endpoint proof | Real execution | Result |
| --- | --- | --- | --- |
| OpenAI | Current production health probe passes | Previously completed production E2E with durable response/usage evidence | **CONNECTED** |
| Google Gemini | Model inventory and health probe pass | `gemini-3.1-flash-lite`, real durable runtime execution | **CONNECTED** |
| OpenRouter | Model inventory and health probe pass | `google/gemma-4-26b-a4b-it:free`, real durable runtime execution | **CONNECTED** |
| Anthropic / Claude | Credential is valid enough to list the account model inventory | `/v1/messages` reaches Anthropic but is refused by the provider because the account credit balance is too low | **EXTERNAL BILLING BLOCKER** |

The Gemini live execution retained non-zero provider usage and latency and the OpenRouter live execution retained non-zero usage with the selected free route. Temporary acceptance agents/jobs were removed after evidence capture; provider connected state, usage/latency state and append-only audit records remain durable.

## Anthropic boundary

The Anthropic key is present and the authenticated model inventory endpoint succeeds. The actual message execution returns an Anthropic `invalid_request_error` stating that the API credit balance is too low. AIOS therefore does not call Anthropic `connected`. This is an operator-owned external billing activation boundary, not a synthetic success and not a reason to substitute an OpenRouter Claude route as proof of direct Anthropic connectivity.

Once Anthropic credit is added, rerun one bounded low-output message through the same durable `run_job` path. Only a completed real job may move the direct Anthropic provider to `connected`.

## Other agent providers

Mistral, Cohere, xAI, DeepSeek, Groq, Together AI, Fireworks AI, Hugging Face and Azure OpenAI do not currently have production credentials. AWS Bedrock has a general AWS credential pair available for other platform uses but no Bedrock region is configured, so it is not activated as a Bedrock runtime. Ollama has no configured production local runtime. These providers stay `unconfigured` and are not claimed live.

## Retained operator evidence

Sanitized production evidence is retained outside Git at:

`/root/.config/aionex/releases/provider-live-matrix-20260811T182133Z`

The final sanitized receipt SHA-256 is:

`c4d703fec1a802235493b5c292c3044f41d0c7165860a8bea5346f0c09b968e2`

## Release rule

`configured != tested != connected`. A provider is `connected` only after a real provider execution passes through the production adapter and durable runtime. External account funding, provider entitlement or credentials remain explicit activation boundaries and never receive fake success.
