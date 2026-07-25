# AIS-0017 — AI Providers Implementation

## Scope
Concrete implementations for OpenAI, Anthropic Claude, Google Gemini, OpenRouter, and Ollama.

## Architectural rules
1. Provider implementations extend the stable `BaseAIProvider` contract.
2. External SDKs are optional and isolated behind injected transports.
3. No credentials are stored in source code, tests, logs, or release archives.
4. Requests and responses are normalized at the provider boundary.
5. Retry and rate-limit behavior is provider-local and configurable.
6. Streaming must expose a provider-neutral asynchronous text iterator.
7. Provider-specific capabilities must not leak into the kernel.
8. Existing Phase 7 Part 1 platform and transport behavior remains compatible.
