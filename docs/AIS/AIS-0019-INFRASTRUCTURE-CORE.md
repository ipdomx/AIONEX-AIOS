# AIS-0019 — Infrastructure Core

## Status
Accepted — Phase 8 Part 1

## Purpose
Establish the contract-based infrastructure layer used by SSH, source-control, container,
cloud, database, DNS, storage and secrets integrations.

## Components
- `BaseInfrastructureIntegration`
- `IntegrationRegistry`
- `ConnectionManager`
- `CredentialsManager`
- `SecretsVault`
- `InfrastructureHealthMonitor`
- `InfrastructureConfigLoader`
- `InfrastructurePlatform`

## Security Rules
- Plaintext credentials are never retained in the credential registry.
- Secret storage is accessed through a pluggable backend contract.
- Default in-memory storage is intended for tests and local bootstrap only.
- Production backends will be added in later Phase 8 parts.

## Extension Rule
New infrastructure providers implement `BaseInfrastructureIntegration` and register through
`IntegrationRegistry`; core modules must not depend on provider-specific SDKs.
