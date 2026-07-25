# AIOS v2.0.0-alpha.8 — Enterprise Foundation

This release introduces the first isolated enterprise runtime layer:

- Versioned Contract Registry
- Idempotent internal Service Bus
- Capability Registry with trust-aware selection
- Tenant isolation context
- Central Policy Engine and owner-only gates
- Durable checkpointed workflows
- Append-only hash-chained observability ledger
- API Gateway authorization and rate limiting
- Signed, API-versioned Plugin Runtime
- AIOS Internal Standards for module boundaries, events, and plugins

All additions are contained under `src/aios/enterprise/` and communicate through public interfaces. Existing subsystems are not moved or overwritten except for minimal kernel wiring and version metadata.
