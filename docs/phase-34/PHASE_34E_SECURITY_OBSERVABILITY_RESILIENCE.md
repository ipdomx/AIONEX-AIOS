# Phase 34E — Security, Observability, Cost and Resilience

## Runtime controls

The 3D product runtime is fail-closed and Owner governed. Every project request receives a durable trace identifier and deterministic request fingerprint. Repeated requests inside the configured duplicate window resolve to the existing job; explicit `Idempotency-Key` values remain stable across client retries.

A durable RunPod circuit breaker is stored in the Owner control plane. Repeated provider submission/status/timeout failures open the circuit at the configured threshold, block new admissions with a sanitized 503, notify the Super Owner, and automatically move to half-open after the configured recovery window. A successful live provider completion closes the circuit. The Super Owner can inspect or reset the circuit from `/owner/3d`.

## Observability

Owner operations expose durable metrics for job totals, active/completed/failed/cancelled counts, success rate, average end-to-end job duration, average provider queue/cold-start delay, average GPU execution runtime, daily/monthly GPU spend, and circuit state. The private Owner endpoint `/api/v1/owner/3d/metrics` exports the same runtime measurements in Prometheus text format. Worker logs include `job_id`, `trace_id`, provider job id, timings, cost, artifact size, error code and circuit state without provider secrets.

## Cleanup and retention

The worker periodically expires S3 artifacts whose Owner-defined retention window has elapsed and idempotently removes stale terminal-job source inputs. The cleanup interval, batch size, artifact retention and temporary input retention are all Owner controls. A manual audited cleanup is available from the Owner 3D page.

## Cost controls

Admission remains bounded by per-user concurrency and monthly generation quotas, maximum per-job cost, daily and monthly spend ceilings. After successful metering, threshold notifications are sent to the Super Owner once per daily/monthly bucket using deduplicated notification keys. New work is rejected before GPU submission when a spend ceiling would be exceeded.

## Supply-chain gate

Backend runtime dependencies are exact-pinned. CI builds the production backend image, emits a CycloneDX SBOM with Syft, and fails on HIGH or CRITICAL Trivy image vulnerabilities. GitHub actions used by the gate are pinned to immutable commit SHAs.

## Disaster recovery / rollback

1. Disable `enabled` on the Owner 3D policy to stop new admissions while preserving records.
2. Scale/restart `three-d-worker` only after the database is healthy; queued jobs remain durable and leases are reclaimable.
3. If RunPod is degraded, the circuit breaker prevents new submissions and existing provider job IDs remain recorded for cancellation/reconciliation.
4. S3 artifacts remain private and are addressed by durable object keys plus SHA-256 checksums; database backups therefore restore metadata without requiring public objects.
5. Application rollback uses the previous known-good Git commit/image and `alembic downgrade 20260809_0013` only if rolling back Phase 34E schema changes. The downgrade removes tracing/idempotency columns after application rollback and must not be run while a newer worker is active.
6. Reapply the current `RUNPOD_GPU.env` secret after restore; secrets are not part of Git or database backups.
7. After rollback or restore, verify `/health`, `/ready`, `three-d-worker --healthcheck`, S3 preflight, RunPod endpoint health, migration head and the Owner 3D operations snapshot before re-enabling admissions.

## Acceptance

Phase 34E is complete only when unit/integration suites, migration upgrade/downgrade/upgrade, portal and Owner builds, dependency audits, image SBOM/vulnerability CI, provider-outage/circuit tests, duplicate-protection tests, cleanup tests, cost-alert tests and production smoke checks all pass.

## Acceptance evidence

Pre-merge validation on 2026-08-09 completed with 632/632 repository tests, 356 passed + 1 skipped backend tests in a disposable PostgreSQL/Redis environment, 33 focused Phase 34D/34E + Owner contract tests, Owner dashboard type-check/Arabic coverage/lint/production build, VIP portal six-locale integrity/type-check/lint/build/smoke, and zero npm audit findings. Migration `20260809_0014` passed upgrade → downgrade to `20260809_0013` → upgrade. The hardened Alpine production backend image is pinned to an immutable Python base digest, uses a separate test stage, excludes build/test tooling from runtime, generated a CycloneDX 1.7 SBOM, and passed the Trivy 0.72.0 HIGH/CRITICAL gate with zero findings. Python dependency audit reported no known vulnerabilities.
