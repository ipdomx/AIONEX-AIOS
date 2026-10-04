# FR-25 — New production server migration continuity plan — 2026-10-04

## Status
The Owner purchased the new dedicated production server and received access details. No application data has been uploaded and no migration has started. Old production remains authoritative and unchanged.

## Provider-confirmed hardware
Provider technical support confirmed:
- all four 1.92 TB NVMe drives are detected;
- RAID 10 is configured;
- RAID is healthy and fully synchronized with no degraded disks;
- full 128 GB RAM is detected;
- both AMD EPYC 7313 CPUs are detected.

The provider control panel reports Debian 12 x86_64. These statements are provider evidence only; NS-00 requires an independent read-only audit from the new host before any upload.

## Continuity contract
The complete migration path is tracked in docs/project/NEW-SERVER-MIGRATION-ROADMAP.md and structured in PLAN.json under new_server_migration. It covers independent hardware audit, security hardening, storage layout, runtime preparation, source/secrets preparation, backup/restore proof, bulk migration, isolated acceptance, Cloudflare/IP dependency inventory, rehearsal, final delta, production cutover, rollback, observation, capacity/growth verification, monitoring, canonical reconciliation, and old-server retirement.

The old server must not be cancelled until the new server is stable, rollback observation is complete, backup/restore is independently verified, old-IP dependencies are cleared, canonical documentation is reconciled, and the Owner explicitly approves retirement.

## Capacity truth
The canonical release test remains the existing 1,000 authenticated-user multi-project/multi-conversation contract. The new server roadmap additionally requires characterization of a safe growth envelope toward 5,000 users. This is not represented as proof that one host can execute 5,000 simultaneous heavy AI/GPU generations; horizontal scale-out triggers must be measured and documented.

## Secrets
No root password, SSH private key, IPMI credential, recovery key, raw environment file, provider secret, or customer data is recorded in this receipt or roadmap.
