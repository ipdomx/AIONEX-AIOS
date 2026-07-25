# AIS-0014 — Security Platform

The phase-5 security platform performs authorized, defensive, local analysis only.

## Boundaries

- Explicit authorization is mandatory.
- No exploitation, credential use, or intrusive network probing is performed.
- Findings contain redacted evidence, remediation alternatives, and verification steps.
- Security history may be written to a hash-chained append-only ledger.

## Components

- Source and secret scanner
- Dependency and supply-chain manifest analyzer
- Container, cloud, and runtime configuration analyzer
- Evidence-weighted risk engine
- Remediation and verification planner
- Security assessment ledger

External CVE intelligence and active server connectors must be implemented later as signed provider plugins governed by owner policy.
