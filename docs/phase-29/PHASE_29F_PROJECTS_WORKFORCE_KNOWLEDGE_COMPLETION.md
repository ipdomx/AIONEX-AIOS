# Phase 29F — Projects, Workforce, Academy, Knowledge, and Workflows

Status: **complete and verified**

GitHub issue: `#205`

## Completion boundary

Phase 29F completes the provider-neutral daily work plane of AIONEX AIOS. It does not activate any AI model or external model provider. Model and provider activation remains reserved for Phase 29J.

The completed scope includes:

- projects, memberships, lifecycle transitions, retained history, review, approval, cancellation, archive, and search;
- tasks, comments, review and rework cycles, completion, cancellation, and reopening;
- deterministic provider-neutral workflow runs with retained input, output, step evidence, attempts, errors, and cancellation state;
- reports generated from retained database records, protected by SHA-256, downloadable, versioned, and archivable;
- an immediate provider-neutral project execution path that invokes no model, sends no external request, consumes no external tokens, creates a protected evidence manifest, requires Owner approval, and produces a checksum-addressed ZIP delivery;
- digital and human workforce records, governed assignments, reviewers, acceptance criteria, performance evidence, health reports, restrictions, incidents, retraining, supervision, promotion, suspension, restore, and retirement;
- academy courses, enrollments, attempts, assessments, passing rules, certification issuance, and revocation;
- tenant-scoped knowledge ingestion, checksums, provenance, verification and rejection, scoped memory, learning outcomes, verification, and promotion to reusable lessons;
- tenant-scoped global search across projects, tasks, workflows, reports, knowledge, workforce, academy, and lessons;
- user, operator, and Super Owner interfaces for retained Phase 29F evidence.

## Persistence

Migration `20260807_0010` adds and validates durable persistence for:

- `project_memberships`
- `project_events`
- `task_comments`
- `workflow_runs`
- `workforce_members`
- `workforce_assignments`
- `workforce_performance_events`
- `workforce_health_reports`
- `workforce_incidents`
- `academy_courses`
- `academy_enrollments`
- `academy_assessments`
- `academy_certifications`
- `knowledge_items`
- `knowledge_provenance`
- `scoped_memories`
- `learning_events`
- `lessons`

The migration also enriches projects, tasks, workflows, reports, and project executions with versioned review, archive, cancellation, rework, evidence, and approval state. Existing active-project execution uniqueness is retained.

## API and service evidence

Core services:

- `web-dashboard/backend/app/services/work_management.py`
- `web-dashboard/backend/app/services/workforce.py`
- `web-dashboard/backend/app/services/knowledge_learning.py`

Tenant APIs:

- `projects.py`
- `project_executions.py`
- `tasks.py`
- `workflows.py`
- `reports.py`
- `search.py`
- `workforce.py`
- `academy.py`
- `knowledge.py`

All mutable paths are tenant-scoped, permission-checked, versioned where relevant, and recorded in audit history.

## Interface evidence

Operator interfaces:

- `/projects`
- `/tasks`
- `/workflows`
- `/reports`
- `/workforce`
- `/academy`
- `/knowledge`

Super Owner interfaces:

- `/owner/projects`
- `/owner/staff`

User portal:

- localized project creation and execution in all six portal languages;
- provider-neutral execution is the default Phase 29F path;
- project evidence can be approved and downloaded without linking `ai.vip-e.net` to the server;
- no external provider or model is represented as active.

## Provider-neutral execution guarantee

For `mode=provider_neutral`:

- `confirm_external_processing` is false;
- provider is reported as `provider-neutral`;
- model is null;
- external request count is zero;
- token counts are zero;
- external cost is zero;
- no production deployment is performed;
- the evidence manifest explicitly states that no model or external provider was invoked;
- the delivery package and Owner approval receipt are checksum protected.

## Verification gates

The Phase 29F validation suite covers:

- full project, task, workflow, report, download, approval, and tenant-isolation cycles;
- workforce assignment, health, incident, retraining, assessment, certification, promotion, suspension, and retirement;
- knowledge provenance, verification, search, memory, learning events, and promoted lessons;
- permission denial and cross-tenant non-disclosure;
- fresh PostgreSQL migration application and active execution uniqueness;
- compatibility with all previously completed backend contracts.

Final verified counts and deployment evidence are recorded in the merged pull request and issue closure report.

## Deployment rule

Phase 29F may update the live backend and private Owner dashboard after backup and migration validation. It does not change Cloudflare DNS and does not link `ai.vip-e.net` to the server. The final static portal package remains deferred until Phase 29J, in accordance with the established project release rule.
