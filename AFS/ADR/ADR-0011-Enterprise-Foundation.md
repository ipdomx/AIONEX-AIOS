# ADR-0011: Enterprise Foundation and Module Isolation

## Status
Accepted

## Decision
AIOS modules communicate through versioned contracts and events. Direct access to another module's internal files, database tables, or implementation details is prohibited.

The enterprise foundation provides a service bus, contract and capability registries, tenant isolation, centralized policy decisions, durable workflows, an append-only audit chain, an API gateway boundary, and a signed plugin runtime.

## Consequences
- Modules can evolve independently when contracts remain compatible.
- Duplicate event delivery is prevented through correlation identifiers.
- High-risk actions remain owner-controlled.
- Workflows resume from persisted checkpoints after failures.
- Plugins cannot enter the trusted runtime unsigned by default.
