# AIS-0018 — AI Routing Layer

Phase 7 Part 3 introduces a provider-neutral routing runtime above the Phase 7 provider contracts.

## Components

- automatic model selection and ranked routes
- cost, speed, quality, privacy, balanced, and offline optimization
- single and parallel model execution
- consensus, voting, and best-result selection
- provider failover and health-aware routing
- bounded concurrency, priority queue, and request scheduling
- provider/model heartbeat, latency, failure, and availability state
- token, cost, speed, success, and error reports
- routing policies for provider priority, exclusions, timeout, retry, budget, privacy, and offline operation

The layer depends only on provider contracts and registries. New providers remain loadable without routing-core changes.
