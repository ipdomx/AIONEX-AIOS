# Owner Dashboard production-readiness audit

Audit baseline: `main` at `60ff89a` (after PR #130).

The audit compared every App Router page below with the shared Owner navigation
registry, the Sidebar and command/search navigation, the authenticated frontend
client calls, the registered FastAPI routes, and the persistence or live probe
behind each action.

## Baseline classification

- **Works fully:** 19 routes already used a dedicated backend adapter or were
  navigation/readiness utilities.
- **UI present but actions unbound:** 23 routes used static arrays, local state,
  or buttons that did not mutate a durable backend.
- **Internal Server Error:** no deterministic route-level 500 was reproducible
  from the baseline source. Database readiness and migration gaps were handled
  as deployment risks in this change rather than relabelled as a page failure.
- **Placeholder:** no literal `This page is under development` remained after
  PR #130 inside `/owner`. The shared Sidebar still appended 13 unrelated
  non-Owner placeholder routes for Super Owners; this change removes those
  routes from the Owner navigation surface.
- **Route unbound:** none; all 41 child routes plus `/owner` were already in the
  central navigation registry.

## Final classification

- **Works fully:** all 42 Owner routes listed below.
- **Internal Server Error:** 0 routes.
- **Placeholder:** 0 routes.
- **UI present but actions unbound:** 0 routes.
- **Route unbound:** 0 routes.

The final classification is backed by live or persistent application sources,
explicit button handlers, registered authenticated API contracts, production
frontend generation, and the release gates described below.

## Per-page result

| Route | Baseline classification | Production source after this change |
| --- | --- | --- |
| `/owner` | Works fully | Navigation registry plus live executive SQL metrics |
| `/owner/access` | UI present but actions unbound | SQL roles and protected suspend/restore actions |
| `/owner/approvals-live` | Works fully | SQL meeting approvals with audit records |
| `/owner/approvals` | UI present but actions unbound | SQL meeting approvals with audit records |
| `/owner/audit` | UI present but actions unbound | SQL audit and Owner command records |
| `/owner/billing` | UI present but actions unbound | Durable Owner billing-control records |
| `/owner/communications` | UI present but actions unbound | Durable channel policy, in-app delivery, and real SMTP test |
| `/owner/completion` | Works fully | Live dependency and release-readiness checks |
| `/owner/compliance-runtime` | Works fully | SQL compliance controls and evidence-backed attestation |
| `/owner/compliance` | UI present but actions unbound | SQL compliance controls; compliant state requires evidence |
| `/owner/costs` | UI present but actions unbound | Durable budget targets with honest telemetry availability |
| `/owner/executive-bi` | Works fully | SQL operational, incident, and project aggregates |
| `/owner/executive` | UI present but actions unbound | SQL executive metrics and release evidence |
| `/owner/final-platform-integration` | Works fully | Live health/release gates and audited closure decision |
| `/owner/finalization` | Works fully | Live dependency and evidence-backed finalization snapshot |
| `/owner/global-command` | UI present but actions unbound | Audited SQL project/service actions and live validation |
| `/owner/governance` | UI present but actions unbound | Durable decisions with audited approve/reject actions |
| `/owner/health` | UI present but actions unbound | Live PostgreSQL, Redis, alert, and readiness probes |
| `/owner/incidents` | UI present but actions unbound | SQL alerts with investigate/resolve actions |
| `/owner/integrations` | UI present but actions unbound | Deployment configuration registry plus supported live probes |
| `/owner/licensing` | Works fully | Durable licenses and audited suspend/restore actions |
| `/owner/notification-runtime` | Works fully | Durable routing declarations and audited toggles |
| `/owner/notifications` | UI present but actions unbound | SQL notifications and real read-state mutations |
| `/owner/operations-integration` | Works fully | Live health, verified backup artifacts, and queued restore/DR execution |
| `/owner/operations` | Works fully | SQL organization, project, and user operations |
| `/owner/organizations` | UI present but actions unbound | SQL organizations, subscriptions, restrictions, and sessions |
| `/owner/platform-integration` | Works fully | Registered integrations and supported live validation probes |
| `/owner/policies` | UI present but actions unbound | Durable policy registry; enforcement is declared honestly |
| `/owner/production-runtime` | Works fully | Live environment, API, data, and runtime readiness |
| `/owner/projects` | UI present but actions unbound | SQL projects shared with the standard project/task workflow |
| `/owner/realtime` | Works fully | SQL metrics, workers, alerts, and recent events |
| `/owner/recovery` | UI present but actions unbound | Durable backup worker, protected artifacts, and real restore/DR validation |
| `/owner/release-governance` | Works fully | Durable release registry and evidence-gated decisions |
| `/owner/release` | UI present but actions unbound | SQL release gates and explicit audited approval |
| `/owner/runtime` | Works fully | SQL projects, organizations, users, and status |
| `/owner/search` | Works fully | Central route registry plus authenticated Owner resources |
| `/owner/secrets` | UI present but actions unbound | External vault references only; no plaintext secret storage |
| `/owner/security-integration` | Works fully | SQL identity, alert, secret-reference, and compliance evidence |
| `/owner/services` | UI present but actions unbound | Durable service policy enforced by AI runtime consumers |
| `/owner/staff` | UI present but actions unbound | SQL users, roles, organizations, and account status |
| `/owner/system-map` | UI present but actions unbound | Live API host, PostgreSQL, and Redis topology/probes |
| `/owner/timeline` | Works fully | SQL audit, command, incident, and release activity |

## Completion gates

Automated contracts fail if any Owner page is missing from navigation, any
literal Owner link is broken, an Owner API client calls an unregistered route,
an Owner mutation lacks `Super Owner` authorization, a data page reintroduces a
mock array, a button has no explicit handler, or the Super Owner Sidebar
reintroduces non-Owner placeholder sections. Database-backed integration tests
additionally verify that standard APIs and Owner pages observe the same project,
meeting, notification, alert, metric, and recovery rows.

The production container applies Alembic before bootstrap/startup, verifies the
exact schema head, supports both the current `POSTGRES_*` contract and legacy
bundled `DATABASE_URL` passwords as the compatibility source while requiring
the same PostgreSQL user and database, and keeps
`scripts/reconcile-postgres-credentials.sh` compatible with both development
and production Compose projects. A one-shot authenticated reconciliation gate
runs before the backend, skips valid external URLs, rejects malformed bundled
values and identity conflicts before local mutation, does not expose plaintext
credentials, and never deletes a database volume.
