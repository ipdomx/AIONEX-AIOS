# FR-20A communications inventory acceptance — 2026-10-04

Run: `fr20-scheduled-20261004T0041Z-6ac041f5-r10`  
Task: `6ac041f5fa4481918e5b4512dc24436b`  
Batch: `FR-20`  
Origin main: `7779f740a81d4fae2167c8441218b69e54cf56f5`  
Policy SHA256: `e10a48f32f2aaf7e699e410c67ce93ab3f326d2e784d0e9dcf9c8f8a77fe7582`  
Coordination helper SHA256: `020e29cd84f5ecc9abb5aa8456b59721687cfa89f3d6e4cde97d128d3b6bf2a5`  
Observed: `2026-10-04T00:47:26Z`

## Scope

This is a source-only FR-20A acceptance package. It changes only:

- `web-dashboard/backend/tests/test_fr20a_communications_inventory.py`
- this receipt

It performs no live provider calls, database calls, credential reads, customer-data access, spend, publication, deployment, or production mutation. It does not retry or requeue historical notification deliveries.

## Acceptance proved

The dedicated test uses only the Python standard library and reads tracked source text/AST. It therefore validates the source contracts without importing the backend runtime or opening provider/DB paths.

1. **Durable in-app first behavior**
   - `_ensure_notification_deliveries` marks `in_app` delivered before the external-readiness branch.
   - An unavailable external channel is classified `unconfigured` with `provider_unconfigured`.
   - Only `queued` deliveries receive `next_attempt_at`; the acceptance itself never invokes retry/claim/dispatch APIs.

2. **Truthful fail-closed email / Telegram / Firebase readiness**
   - `channel_readiness` requires SMTP configuration for email.
   - Telegram readiness is derived separately from owner/user token-file readiness.
   - Firebase readiness requires local Firebase Admin configuration and a readable service-account document whose `project_id` matches.
   - The readiness response schema exposes status/capabilities only; credential material is not an output field.

3. **Firebase boundary**
   - The readiness implementation is local configuration validation only.
   - The tested readiness function contains no provider-network/OAuth execution path and therefore is not evidence of live Firebase/OAuth health.

4. **Connected-social / OAuth classification**
   - `growth_provider_connectors.py` keeps contract validation `unverified`, with `provider_call_allowed=false`, `mutation_allowed=false`, and `spend_allowed=false`.
   - Live mutation modes remain blocked and credential references are required.
   - The shared connector planner is classification/planning evidence, not proof that a provider is connected or live-verified.

5. **Simulator truth**
   - `growth_social_accounts.py` labels capability evidence `simulated`.
   - Simulator output explicitly carries `live_verified=false` and `live_provider_call=false`.
   - Metadata health may return `healthy`, but the reason is explicitly `metadata-health-simulation-passed`; it is not live provider health.

## Validation

Initial direct pytest collection was attempted and stopped before any test body because the host test environment lacks SQLAlchemy:

`ModuleNotFoundError: No module named 'sqlalchemy'`

No package installation or host-environment mutation was performed. The acceptance test was kept source-only and dependency-free instead of weakening the host boundary.

Successful targeted validation:

- `python3 -m py_compile web-dashboard/backend/tests/test_fr20a_communications_inventory.py` — PASS
- `python3 web-dashboard/backend/tests/test_fr20a_communications_inventory.py -v` — PASS, 6/6
- `git diff --check` — PASS

## Ownership / dependency boundary

No shared growth connector/OAuth execution source was modified; that remains coordinator/FR25-owned. FR19 remains the integration/live/final FR20 dependency. This package is not an integration, deployment, provider-live-health, or final FR20 closure claim.
