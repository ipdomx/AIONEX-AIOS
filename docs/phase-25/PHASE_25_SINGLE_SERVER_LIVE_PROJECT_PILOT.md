# Phase 25 — Single-Server Live Project Pilot

## Status

Phase 25 completed its production activation and first real user-style project cycle successfully on 2026-08-05.

The implementation was merged through PR `#185` at merge commit `12fb98375c7659089415f1d42e7ed9a0f5e9e176`. All nine GitHub checks passed, including backend tests, production Docker build, CodeQL, dependency security, and Docker DNS re-resolution.

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

## Production activation evidence

The activation followed the protected sequence:

1. A pre-migration PostgreSQL custom-format dump was created, verified with `pg_restore --list`, hashed, and stored root-only with mode `600`.
2. Alembic advanced from `20260802_0005` to `20260805_0006`.
3. The backend was safely recreated and returned healthy.
4. The optional `project-worker` profile was started and returned healthy.
5. The backup worker was recreated from the validated image and returned healthy.
6. A controlled Manager account, workspace, and real project were created.
7. Login, project creation, execution enqueue, status polling, and logout were all exercised through the public API gateway at `api.vip-e.net`.
8. The temporary pilot identity was disabled, its refresh sessions were revoked, and its credentials/session files were removed.

The production services remained healthy after the cycle: Nginx, Backend, Frontend, Project Worker, Backup Worker, PostgreSQL, and Redis were healthy; Cloudflared remained running.

## Real project cycle result

Project: `AIONEX Social Growth Campaign Orchestrator`.

The real objective requested a low-cost bilingual Arabic/English social-media campaign management product with secure accounts, campaign planning, content calendars, approvals, analytics, notifications, Android, iOS, and Telegram delivery.

The durable production result recorded:

- status: `completed`;
- stage: `rework_required`;
- provider/model: `openai` / `gpt-5-mini`;
- department artifacts: `6`;
- provider requests: `6`;
- retries: `0`;
- input tokens: `2,389`;
- output tokens: `3,414`;
- total tokens: `5,803`;
- calculated cost: `0.00742525 USD`;
- fixed budget cap: `0.05 USD`;
- provider execution duration: `96.441046` seconds;
- readiness score: `0.82`;
- fallback used: `false`;
- production modified by the cycle: `false`.

`approved=false` is a truthful planning result rather than an execution failure. The model produced implementation plans but did not claim that department tests or security reviews had already happened. The stored rework plan therefore requires those gates before implementation approval.

The evidence validation confirmed six artifacts, one durable completion notification, three execution audit events, released job lease, no stored provider secret, no Authorization header, no raw prompt, and no raw provider response. The project moved to `active` with initial progress `25%` after the planning stage completed.

## Portal release

The multilingual static user portal release is now version `1.3.0`. Its TypeScript, lint, static build, and static smoke checks passed. The generated package is ready for the existing `ai.vip-e.net` shared-hosting document root.

The server does not contain a configured FTP/SFTP/cPanel deployment credential for that external hosting account. Therefore the package is prepared and retained securely, but no hosting credential was guessed or fabricated. The live API and worker are active; publishing the new portal assets requires a real authenticated deployment channel to the separate hosting provider.

Android, iOS, and Telegram validation/publication follow this proven real web project cycle.
