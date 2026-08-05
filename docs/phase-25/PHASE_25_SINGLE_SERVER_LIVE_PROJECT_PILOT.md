# Phase 25 — Single-Server Live Project Pilot

## Status

Implementation and isolated validation are complete. Production activation and the first real user-style project cycle are intentionally performed only after the pull request passes CI and is merged.

Phase 25 keeps AIONEX AIOS on the current server. It does not require or provision another VPS. The public user portal remains separate from the private Owner Dashboard, while the authenticated project execution API and a dedicated worker run inside the existing production stack.

## Goal

Allow an authorized portal user to create a real project and explicitly start one bounded AI planning cycle. The cycle sends only the project name, objective, department, and generic acceptance criteria to the configured OpenAI model. It produces six department artifacts, a review, a comparison, and a truthful rework plan without modifying production application code or infrastructure.

## Budget boundary

Each project can create one pilot execution record. The worker applies all of these fixed limits:

- provider: OpenAI only;
- allowed model: `gpt-5-mini` or its pinned snapshot;
- exactly six department requests at most;
- no automatic department retry;
- maximum 1,200 output tokens per request;
- maximum 4,096 input-token safety allowance per request;
- maximum execution budget: `0.05 USD`;
- no fallback provider;
- no tools or web browsing;
- no parallel provider requests.

The configured worst-case six-request estimate remains below the fixed cap. Actual cost is calculated from provider-reported token usage and recorded in the durable job result.

## Durable backend

The new `project_executions` table stores:

- tenant, workspace, project, and requesting user;
- explicit external-processing consent;
- queued/running/completed/failed status;
- stage and progress;
- lease and bounded attempts;
- provider/model and budget cap;
- request, token, retry, duration, and calculated-cost metrics;
- approval, readiness, blockers, and rework summary;
- sanitized error details and an internal evidence location.

The API never returns filesystem evidence paths, credentials, prompts, raw provider responses, or authorization headers.

## API

Authenticated project routes add:

- `POST /api/v1/projects/{project_id}/executions`;
- `GET /api/v1/projects/{project_id}/executions`;
- `GET /api/v1/projects/{project_id}/executions/{execution_id}`.

Starting a cycle requires explicit confirmation that the project name and objective may be processed by the configured external provider. Organization isolation and existing `projects:read` / `projects:write` permissions remain enforced.

Free-tier users consume one user-message unit and one assistant-response unit when the durable job is accepted. The existing one-project quota still applies only to creating a project, not to starting the project’s single planning cycle.

## Worker and evidence

The optional Compose profile `ai-execution` adds `project-worker` without changing the normal production startup path.

The worker:

- claims durable jobs with PostgreSQL `SKIP LOCKED`;
- maintains a lease heartbeat;
- uses a root-readable external secret only through the protected container entrypoint;
- copies the retained Phase 22B local reference into a private runtime path;
- writes runtime evidence to a named volume;
- recovers a completed manifest instead of sending a duplicate paid request if a database commit was interrupted;
- updates the project, creates a user notification, and appends audit evidence;
- reports sanitized terminal failures.

The secret and retained local-model evidence are read-only inputs. The source repository is mounted read-only. Production services are not modified by the planning cycle itself.

## User portal

The six-language static portal now:

- loads the latest execution for every project;
- asks for explicit external-provider confirmation;
- starts the cycle;
- polls queued and running jobs;
- displays stage, progress, calculated cost, readiness, token/request totals, approval, and truthful rework status;
- never displays internal evidence paths or secrets.

## Validation completed before activation

- new Phase 25 backend tests: `5 passed` against an isolated PostgreSQL/Redis environment;
- complete backend suite: `253 passed, 1 skipped`;
- controlled Phase 22C–24B boundary: `170 passed`;
- root release/web/production contracts: `8 passed`;
- VIP Frontend TypeScript: passed;
- VIP Frontend lint: passed;
- static build: 67 pages generated;
- static smoke: 64 URLs passed;
- production Compose validation: passed for both supported Compose definitions;
- backend image build: passed;
- non-root worker secret/reference/output preparation: passed;
- source compilation, diff whitespace, and credential-shaped-value scans: passed.

## Activation sequence after merge

1. Create a protected pre-migration PostgreSQL backup.
2. Apply Alembic revision `20260805_0006`.
3. Rebuild and safely recreate the backend.
4. Start only the optional `project-worker` profile.
5. Confirm backend, worker, PostgreSQL, Redis, Nginx, frontend, backup worker, and Cloudflare Tunnel health.
6. Create a controlled internal pilot account and project.
7. Start the cycle through the public authenticated API.
8. Poll it to a terminal state and verify cost, evidence, notifications, audit records, and production health.
9. Remove temporary pilot credentials.
10. Publish the rebuilt static portal package to the existing user-portal hosting path when the configured deployment channel is available.

Android, iOS, and Telegram validation/publication follow only after this real web project cycle is proven.
