# AIS-0016 — AI Providers & Multi-Model Platform

## Purpose
Provide a vendor-neutral provider layer with policy, privacy, cost, health, routing, metrics, and multi-model comparison.

## Mandatory rules
1. No API key is stored in source code or release archives.
2. Restricted data may only be routed to local providers.
3. The owner can enable or disable any provider.
4. Project policy and budget are evaluated before routing.
5. Provider adapters depend only on the stable provider contract.
6. New providers are registered without modifying the kernel internals.
