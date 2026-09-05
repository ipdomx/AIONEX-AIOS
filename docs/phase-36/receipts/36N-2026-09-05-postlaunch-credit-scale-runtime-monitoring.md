# Phase 36N — Post-launch Provider Credit, Runtime Monitoring, and Multi-Project Scale

- Date: 2026-09-05
- Scope: post-launch hardening after the final PR #550 production certification.
- Source branch: `postlaunch-credit-scale-20260905`, based on merged production `main` `146107b071ba737c0d95b2388490203bd4aeb604`.

## Owner goal

Prepare AIONEX for more than 100 concurrent authenticated users while allowing one user/tenant to work on multiple independent projects at the same time, and notify the Super Owner before paid AI capacity is affected by low credit or provider billing/quota failures. Add production runtime/restart alerts without granting the application Docker-socket access.

## Multi-project and admission result

A fresh isolated PostgreSQL 16 + Redis 7 environment was migrated from an empty database through Alembic `20260905_0044`. The production-shaped distributed admission contract retained the existing API DB pool `12+2`, DB budget `60`, Redis pool `18`, local admission `14`, global admission `48`, and four admission processes.

A new workload admitted **150 tenants/users x 3 distinct projects each = 450 durable ProjectExecution submissions** through the real Redis lease + PostgreSQL admission path:

- admitted: `450/450`
- unique execution IDs: `450/450`
- tenants: `150`
- projects per tenant: exactly `3`
- lost submissions: `0`
- duplicate submissions: `0`
- provider attempts before worker claim: `0`
- Redis admission leases after completion: `0`
- p95 admission latency: `0.867s`
- maximum admission latency: `0.894s`

A separate scheduler acceptance proved three queued projects from the same tenant can be claimed into `running` concurrently when the tenant active limit is `6`.

The same-host production target is **4 Project Worker replicas x capacity 3 = 12 simultaneous heavy ProjectExecution slots**, with `PROJECT_EXECUTION_TENANT_ACTIVE_LIMIT=6`. This intentionally does **not** claim 450 simultaneous provider-heavy builds. Work above the 12 same-host execution slots remains durable and queued; per-provider Redis rate/concurrency/circuit guards remain authoritative so a user burst cannot bypass provider limits or cost governance.

The current host observed before activation has 12 logical CPUs and 62 GiB RAM, with approximately 56 GiB available at the measurement point. The 12-slot target is therefore deliberately bounded rather than an unlimited concurrency setting.

## Provider credit monitoring

The existing `owner_attested` finance mode truthfully confirms funding and detects explicit billing/quota failures, but cannot predict depletion without a numeric funded baseline. This change adds `numeric_private` monitoring:

- Funded / Low / Critical numeric values are stored only in the Owner control record.
- General/public finance snapshots hide funded, remaining, and threshold amounts.
- The authenticated Super Owner finance surface can read the private values.
- Low and Critical state is still computed from durable measured Project-AI spend.
- Provider-credit checks run independently every `300s`, rather than waiting for the 15-minute lifecycle scan.
- Low/Critical notifications use the protected Owner channels. Current runtime readiness is `in_app + Telegram`, with email available as fallback.
- `owner_attested` providers now receive a one-time predictive-monitoring-required warning explaining that a numeric funded baseline is required for pre-depletion prediction; explicit billing/quota failures remain monitored immediately.
- No provider balance is invented and no unsupported billing API is claimed.

## Runtime and restart monitoring

Application-level Operations Observer monitoring remains unprivileged and does not receive `/var/run/docker.sock`. It now produces durable Owner alerts for confirmed component unavailability/recovery and active critical platform alerts.

A separate host-side, read-only Docker watcher was added under `scripts/operations/docker-runtime-watch.py` and systemd timer sources under `deploy/systemd/`. It:

- establishes a first-run baseline without alerting healthy services;
- sends an immediate Owner alert when a container restart counter increases;
- requires two consecutive bad polls before declaring a container missing/unhealthy;
- sends recovery alerts;
- retries failed notification delivery by retaining the prior transition state;
- sends only sanitized service/event/counter metadata into the Operations Observer container;
- never mounts the Docker socket into an application container.

## Verification

Pre-merge local gates on the final source:

- focused provider-credit / observer / runtime-alert / host-watch / Compose tests: **17 passed**;
- 150 x 3 project admission + three-running-same-tenant acceptance: **2 passed**;
- Full Backend: **1116 passed, 2 skipped, 0 failed**;
- AIOS Core Owner / Release / Web contracts: **857 passed, 0 failed**;
- Backend Ruff: PASS;
- Backend Mypy: PASS across **254 source files**;
- Owner API contracts + TypeScript: PASS;
- Owner Arabic coverage: PASS, **1019 translatable strings / 5 approved technical tokens**;
- Owner ESLint: PASS, zero warnings/errors;
- Owner Prettier: PASS;
- Owner production Next.js build: PASS, **91 static pages**;
- Owner `npm audit --omit=dev`: **0 vulnerabilities**;
- repository secret/production security audit: PASS;
- repository security audit: PASS;
- both production Compose files render successfully with project-worker scale `4`, worker capacity `3`, tenant active limit `6`, and provider-credit interval `300s`.

A deliberately incorrect full-suite harness with production-style SQLAlchemy pooling was rejected after cross-event-loop asyncpg errors. The official Full Backend rerun restored the suite's test-mode NullPool boundary and passed 1116/2. The separate 450-admission acceptance retains production-shaped pooling, so this correction does not weaken the load evidence.

## Activation boundary

This receipt proves the source, isolated scale behavior, monitoring contracts, and build/test readiness. Protected GitHub review/CI/merge and production activation are still required before these post-launch changes are called live. Production activation must preserve the existing Realtime profile, enable the `ai-execution` profile, recreate the affected Backend/Observer/Project Worker/Owner services from the exact merged tree, install/enable the host runtime timer, and prove four online workers with aggregate capacity 12.
