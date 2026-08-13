# AIONEX AIOS — Core Production Release Candidate Acceptance — 2026-08-13

Status: **CORE_RC_GO**

This document records the production release-candidate acceptance of the AIONEX AIOS core platform. The scope is the platform foundation and production runtime. Payment/mobile-store activation and provider-side quota approvals remain explicit external gates and are not represented as completed here.

## Accepted production baseline

- Production main: `2fe5d8c2bffae4b655b7c261f7cc85cdba18cf92`.
- `main` and `origin/main` matched after deployment and the production working tree was clean.
- Core containers were running and healthy, including backend, backup worker, frontend, portal, PostgreSQL, Redis, project worker, security scan worker and the private Ollama runtime.
- Public site and user portal returned HTTP 200. The Owner hostname remained behind the private/Access boundary.
- Live Production Runtime API reported `completion=100` with database, Redis, backend, runtime-components and operations all `ready`.
- Main-branch Final Validation completed successfully, including the Production Docker Build and backup/restore round-trip.

## User and authorization acceptance

A dedicated synthetic non-Super-Owner acceptance identity was used; no real customer account was modified.

Validated through the live public ingress:

- authenticated public session resolved to a non-Super-Owner role;
- the same session was rejected by the private Owner channel with HTTP 403;
- Owner-only runtime resources were not exposed through the public channel;
- workspace creation returned 201;
- project creation returned 201;
- provider-neutral project execution returned 202 and completed at `progress=100`, stage `review`;
- access-token refresh returned 200;
- disposable project and workspace cleanup returned 200;
- durable audit events were recorded for workspace creation, project creation, provider-neutral completion and cleanup.

The post-fix lifecycle was repeated after deployment and completed successfully again.

## Free-tier limits and entitlements

A disposable synthetic free tenant was created solely for acceptance and deleted at the end of the test.

Validated:

- current free-tier status exposed a project limit of 1;
- free accounts could not mutate the protected personal workspace (HTTP 403);
- first project creation succeeded (201);
- second project creation was rejected by the free-project limit (429);
- billing/usage visibility remained available;
- the temporary free tenant and its dependent state were removed after the test.

## AI runtime and routing acceptance

Production provider state at acceptance:

- 13 providers had completed durable live acceptance and were `connected`;
- Azure OpenAI remained `configured`, awaiting provider-side quota/deployment approval;
- AWS Bedrock remained `configured`, awaiting provider-side inference quota approval.

Live Core `AIRoutingLayer` acceptance used actual production transports:

- direct route selected Groq and returned the exact bounded result `RC_DIRECT_OK`;
- a failure was injected only in the acceptance harness for the primary Groq route; no provider configuration was changed;
- failover selected the private local Ollama runtime and returned `RC_FALLBACK_OK`;
- executed candidates were `groq:failed` followed by `ollama:ok`.

Durable agent-runtime acceptance through the private production API also completed:

- Groq job returned `RC_DURABLE_GROQ_OK`, 64 tokens, with persisted completion state;
- Ollama job returned `RC_DURABLE_OLLAMA_OK`, 52 tokens, with persisted completion state;
- disposable agents were removed after acceptance;
- AI job notifications were visible in the Owner notification center.

## Owner control and audit acceptance

Validated on the private Owner plane:

- non-Super-Owner sessions remained denied;
- Production Runtime returned 100%;
- Owner provider inventory reflected 13 connected providers plus the two configured external quota gates;
- Owner Control global resources exposed tenant projects, organizations, notifications and audit activity;
- the Security Audit page/API now exposes tenant audit events to the Super Owner while preserving organization isolation for non-Super-Owner roles.

## Core defects found and fixed during RC

### 1. Existing tenant built-in role permission drift

Existing tenant built-in roles could predate newly introduced permission codes. The production seed synchronized the platform organization but did not add newly introduced explicit permissions to matching built-in roles in older tenant organizations. This caused a legacy tenant `Owner` role to lack notification/communication permissions.

Fix in PR #301:

- startup performs a narrow, additive backfill only for **existing**, non-deleted tenant roles whose names match assignable built-in roles;
- no missing roles are created;
- no tenant `Super Owner` role can be created;
- tenant-defined/custom roles are untouched;
- existing custom permission assignments are not removed;
- repeated execution is idempotent.

Production dry-run before deployment: `0` new roles, `111` missing role-permission assignments, `0` tenant Super Owner roles.

Post-deployment validation confirmed the existing synthetic tenant Owner had all 58 explicit Owner permissions, including `notifications:read` and `communications:read`, with no wildcard permission. Its notification center returned 200 and its private Owner-plane access remained 403.

### 2. Super Owner Security Audit scope

The dedicated Owner Control audit resource was global, but the standard `/api/v1/security/audit` endpoint used by the Owner Security Audit UI restricted the Super Owner to the platform organization plus global events. Tenant audit events were therefore hidden from that page.

Fix in PR #301:

- Super Owner receives the global audit ledger;
- all other roles remain strictly organization-scoped.

Post-deployment validation confirmed tenant RC audit events were visible through the Super Owner Security Audit API.

## Backup and disaster-recovery acceptance

The protected backup/DR path was exercised without an in-place production restore:

- completed backup artifacts were visible with non-zero size and checksum;
- a DR test was enqueued through the private API;
- the backup worker completed the isolated restore validation;
- final state was `completed`;
- `validated=True` and `dry_run=True`;
- no restore error was reported.

The main-branch Production Docker Build independently passed its backup/restore round-trip after the RC fix was merged.

## CI and security gates

PR #301 (`Fix RC tenant role drift and owner audit scope`) passed all required checks before merge, including:

- Backend Tests;
- Core Owner / Release / Web Contracts;
- Frontend Build;
- Owner and VIP browser boundaries;
- Repository secret and hygiene audit;
- Dependency Security;
- Backend SBOM and vulnerability gate;
- CodeQL for Python and JavaScript/TypeScript;
- Production Docker Build, including legacy database compatibility and backup/restore validation.

Merge commit: `2fe5d8c2bffae4b655b7c261f7cc85cdba18cf92`.

## External / deferred gates

These are **not Core RC defects** and do not change the `CORE_RC_GO` result:

- Azure OpenAI: credentials/resource configured; final live deployment is waiting for Microsoft quota approval.
- AWS Bedrock: credentials/IAM/region configured; final live inference is waiting for AWS quota approval.
- Payments: further commercial payment work is intentionally deferred.
- Apple App Store and Google Play production billing: completion is deferred until external developer-account activation/credentials are available.

## Release decision

**CORE_RC_GO**

The AIONEX AIOS production foundation passed the release-candidate acceptance for authentication boundaries, tenant/project lifecycle, project-worker execution, free-tier enforcement, durable AI execution, live provider routing/failover, notifications, Owner global visibility, audit isolation, runtime health, backup and isolated restore validation.

The appropriate next state is **core feature freeze + controlled pilot/launch-readiness work**, while the documented external gates are completed independently. New feature development should not reopen completed foundation phases unless a production defect or an explicitly approved change requires it.
