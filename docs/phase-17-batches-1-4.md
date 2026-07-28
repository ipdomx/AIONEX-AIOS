# Phase 17 — Plugin SDK & Marketplace (Batches 1–4)

This delivery establishes the first half of the extensibility platform:

- Plugin manifests and package contracts
- Plugin lifecycle registry
- Owner-scoped permission evaluation
- Plugin runtime execution contracts
- Automated tests for lifecycle, ownership, permissions, and execution

## Validation criteria

1. CodeQL passes.
2. Final Validation passes.
3. Plugins cannot be submitted by another owner.
4. Gated permissions require owner approval.
5. Only approved plugins can be published.
6. Runtime execution fails safely for unknown or failing handlers.
