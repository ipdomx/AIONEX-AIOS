# Phase 13 — API Gateway and Final Web Dashboard

Batches 1 through 4 add:

- API gateway route contracts and lifecycle
- Scope-based authorization and per-principal rate limiting
- API key issuance, authentication, ownership, and revocation
- Owner dashboard aggregation API
- Unit tests for authorization, throttling, key lifecycle, and dashboard snapshots

## Completion criteria

1. CodeQL passes.
2. Final Validation passes.
3. Unauthorized scopes are rejected.
4. Revoked API keys cannot authenticate.
5. Rate limits are enforced per principal and route.
6. Owner dashboard data remains owner-scoped.
