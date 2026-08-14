# AIONEX AIOS — Growth & Social Command Center Roadmap — 2026-08-14

Status: **APPROVED_FOR_INCREMENTAL_BUILD**

This document is the live source of truth for the post-RC Growth & Social Command Center expansion. Every batch must update this file before and after implementation. No batch may be treated as complete unless its simulation, tests, pull request, merge, deployment checks, and report evidence are recorded here.

## 1. Product objective

Build an AIOS-native Growth & Social Command Center that allows an authorized user (individual, company, agency, affiliate marketer, or other owner-approved account type) to plan, operate, measure, and improve marketing and social-media work from one place.

The system must support:
- campaign research and planning;
- market, competitor, geographic, audience, and offer analysis;
- audience segmentation and targeting recommendations;
- compliant lead-source ingestion/enrichment with provenance and consent controls;
- content generation, approval, publishing, scheduling, recycling, and cross-posting;
- unified inbox and response workflows when provider APIs permit them;
- analytics, attribution, failure analysis, learning, and replay of successful campaigns;
- paid campaign draft/execution with explicit budget and approval gates;
- account health, OAuth lifecycle, team/RBAC, audit, notifications, integrations, exports, and white-label expansion;
- simulation-first acceptance before any live advertising spend.

AIOS must never promise guaranteed advertising outcomes. It must instead provide bounded forecasts, measurable confidence, stop-loss controls, causal evidence where possible, and explicit reasons for success/failure.

## 2. Owner-controlled availability and service-level permissions

This expansion is **not globally available by default**. The Super Owner controls whether the capability exists for each user/account/organization regardless of free/paid plan.

Access evaluation order for every Growth/Social action:
1. user/account is active and not banned/suspended;
2. organization billing/account state permits normal access;
3. base role permission allows the operation;
4. plan/entitlement allows the class of capability where applicable;
5. owner service-control override allows the exact Growth/Social service;
6. provider connector/account itself is active and healthy;
7. for spend/publish/DM/high-impact automation, an explicit approval policy is satisfied.

The owner must be able to:
- grant or remove the entire Growth & Social module for any user or organization;
- grant/deny individual services independently (campaign research, lead intelligence, publishing, inbox, analytics, paid ads, automations, exports, connectors, etc.);
- override plan defaults without changing the user's commercial plan;
- pause/revoke a capability immediately;
- set per-user or per-organization limits, budgets, connector counts, posting quotas, team limits, and automation permissions;
- require approval for publishing, campaign launch, audience export, or budget changes;
- see an audit trail of every grant, denial, override, execution, and provider action.

No user can self-enable an owner-blocked service.

## 3. Safety, privacy, platform-policy, and spend boundaries

- OAuth/provider tokens remain outside user-visible data and are encrypted/secret-managed; passwords are never collected for supported OAuth providers.
- Personal/contact data may only enter the system from a lawful user-owned source, platform lead form, CRM/import with attestation, consented form, documented business-public source where lawful, or reviewed enrichment provider.
- Each lead/contact record must carry provenance, collection/import time, permitted-purpose metadata, consent/lawful-basis state where required, opt-out/suppression state, and retention policy.
- No private-data scraping, credential bypass, mass unsolicited contact, engagement manipulation, fake metrics, or prohibited follow/unfollow/like automation.
- Provider capability matrices must be truthful: unsupported API functions must not be simulated as live provider functions.
- Real advertising spend is disabled until a later explicit owner gate. Initial batches operate in simulation/draft mode only.
- Every real campaign must later require a maximum budget, daily cap, stop-loss/CPA/ROAS rules where applicable, and approval before spend.

## 4. Architecture

Primary bounded contexts:

1. **Growth Access Control** — owner overrides, entitlements, limits, approval requirements.
2. **Social Account Registry** — provider connectors, multiple accounts per provider, health/token lifecycle/capabilities.
3. **Campaign Intelligence** — business brief, market research, competitor evidence, geography, personas, audience hypotheses, offers, channels, budget scenarios.
4. **Campaign Orchestrator** — campaign/ad-set/ad/creative drafts, approvals, simulations, execution lifecycle, stop-loss and replay.
5. **Content Operations** — media library, templates, drafts, approval, scheduler, queue, cross-post customization, recycling.
6. **Inbox & CRM** — messages/comments/mentions, assignment, notes, sentiment, spam, quick replies, supported automations.
7. **Lead Intelligence** — compliant sources, normalization, dedupe, consent/provenance, scoring, enrichment adapters, suppression.
8. **Analytics & Learning** — metrics, attribution, experiments, anomaly/failure analysis, successful-pattern memory, recommendations.
9. **Integrations & Export** — GA, CRM, email marketing, cloud storage, sheets, webhooks, reports and later white-label/custom domain.

Every provider adapter exposes a capability matrix rather than assuming feature parity.

## 5. Delivery protocol — mandatory for every batch

For **each batch**, in this order:
1. update this roadmap with planned scope and status `IN_PROGRESS`;
2. create an isolated Git branch/worktree from current `origin/main`;
3. implement only that batch;
4. run static/unit/contract tests;
5. run a deterministic **simulation** proving the batch behavior without real advertising spend;
6. run regression gates relevant to existing AIOS boundaries;
7. open a PR;
8. wait for all required GitHub gates to pass;
9. merge to `main`;
10. deploy only the affected runtime components when deployment is required;
11. run post-merge/post-deploy checks;
12. update this roadmap with evidence, merge commit, tests, simulation results, risks, and next batch;
13. commit/merge the report update before starting the next batch.

No batch may be skipped, silently combined, or marked complete without evidence.

## 6. Build batches

### GS-01 — Growth access-control foundation
Status: **COMPLETE**

Build durable owner-controlled Growth/Social service access. Reuse current User/Role/Billing/OwnerControl/Audit foundations. Add a canonical capability catalogue and effective-access resolver supporting global module grant/deny, service-specific overrides, limits, approval requirements, and plan/role composition.

Acceptance:
- owner can grant/deny individual Growth/Social capabilities without changing plan;
- owner deny always wins;
- suspended/banned/unavailable account is denied;
- effective permissions are recalculated at request time;
- every mutation is audited;
- simulation covers free user granted a feature, paid user denied the same feature, owner override, suspension, and immediate revocation.

### GS-02 — Campaign intelligence domain + simulation engine
Status: **PLANNED**

Durable campaign briefs, objectives, market/geography/competitor/audience hypotheses, offers, channels, budget scenarios, confidence/evidence fields, and deterministic simulation output. No provider spend.

### GS-03 — Social account registry + provider capability matrix
Status: **PLANNED**

Multiple accounts/provider, OAuth state/health metadata, token-expiry model, pause, team assignment, capability matrix, connector simulator. No credentials committed.

### GS-04 — Content operations foundation
Status: **PLANNED**

Drafts, platform variants, media references, approvals, scheduler, queue, recycle, UTM generation, preview contracts, simulated publishing adapters.

### GS-05 — Analytics & learning ledger
Status: **PLANNED**

Normalized metrics, experiment/campaign outcomes, failure reason taxonomy, successful-pattern records, recommendations, replay eligibility and anti-repeat rules.

### GS-06 — Lead intelligence & compliant audience data
Status: **PLANNED**

Source provenance, consent/lawful-basis metadata, dedupe, suppression, retention, imports, provider lead forms, enrichment interface, audience eligibility evaluator. No unauthorized scraping.

### GS-07 — Unified inbox & CRM workflow
Status: **PLANNED**

Conversations/messages/comments/mentions, read state, assignment, notes, sentiment/spam classification, templates, supported auto-replies with approval/policy constraints, simulated provider events.

### GS-08 — Paid campaign orchestrator (simulation only)
Status: **PLANNED**

Campaign/ad-set/ad/creative lifecycle, budget/day caps, approvals, stop-loss rules, A/B experiments, launch simulation, pause/scale/replay decisions. `real_spend_allowed=false` hard gate.

### GS-09 — First live provider connectors
Status: **PLANNED_EXTERNAL_GATES**

Implement provider-specific OAuth/API connectors only where owner credentials/apps and platform approvals are available. Each connector gets separate capability tests and a live no-spend/read-only or sandbox validation before any mutation.

### GS-10 — Advanced integrations, exports, teams and reports
Status: **PLANNED**

CRM/email/cloud/sheets/webhooks/report exports, richer team workflows, scheduled reporting, PDF/Excel generation, white-label/custom-domain foundations where compatible with the current platform architecture.

### GS-11 — Full-system synthetic acceptance
Status: **PLANNED**

A complete synthetic journey from owner entitlement grant → account connection simulator → research → plan → content → campaign simulation → inbox/lead events → analytics → failure learning → successful replay recommendation → revocation. No real spend.

### GS-12 — Controlled live pilot gate
Status: **BLOCKED_UNTIL_EXPLICIT_OWNER_APPROVAL**

Real human account/provider pilot only after all previous batches are merged and green. Real advertising spend remains disabled until explicit owner approval, provider credentials, legal/policy prerequisites, and defined budget/stop-loss controls are present.

## 7. Current execution log

### 2026-08-14 — Roadmap initialization
- `main` verified clean and synchronized with `origin/main` before development.
- Growth & Social Command Center requirements approved by owner.
- Owner-controlled per-user/per-organization/per-service access is mandatory and independent of free/paid plan defaults.
- Simulation-first development and per-batch report-before-next-batch protocol are mandatory.
- Real advertising spend remains disabled.
- Next action: begin **GS-01 — Growth access-control foundation**.

### GS-01 implementation checkpoint — 2026-08-14
- Durable Growth/Social capability catalogue implemented.
- Effective access resolver composes active-user state, billing state, plan entitlements, and owner user/organization overrides.
- Owner deny wins; owner grant can enable a free user independently of plan.
- Per-capability approval requirements and limits are supported.
- Super Owner mutation endpoints and authenticated user access snapshot endpoint added.
- Every owner override mutation is audited.
- Deterministic simulation proves free-user grant, paid entitlement, owner deny, immediate revocation, and zero-spend limit.
- Local focused tests: 6/6 Growth access tests PASS; roadmap/completion contracts: 9/9 PASS.
- No provider OAuth, publishing, lead extraction, or real advertising spend introduced.


### GS-01 completion — 2026-08-14
- PR #310 merged to `main` as `7c01cd815c7beee1ab7f191686e66fc5f998e326`.
- All required GitHub gates passed, including Backend Tests, Core Owner / Release / Web Contracts, Policy/Resilience, Frontend Build, Owner/VIP browser boundaries, CodeQL, Dependency Security, SBOM/vulnerability gate, and Production Docker Build.
- Post-merge deployment rebuilt the production backend from `main`; backend returned healthy.
- Live ingress validation found the authenticated Growth/Social access snapshot was initially blocked by the public Nginx allowlist (HTTP 404).
- The ingress defect was fixed in PR #311 and merged as `9aaff9a`; regression coverage now allows only `/api/v1/growth-social/access` on the public channel while keeping `/api/v1/owner/growth-social/*` private.
- Post-fix live check: unauthenticated `/api/v1/growth-social/access` returns HTTP 401 from the backend, proving the route reaches application auth; unlisted owner surfaces remain outside the public allowlist.
- GS-01 remains simulation/control-plane only: no OAuth provider connection, publishing, lead extraction, campaign launch, or real advertising spend was introduced.
- Real advertising spend remains disabled by roadmap policy and no spend execution path exists in GS-01.
- Next batch: **GS-02 — Campaign intelligence domain + simulation engine**.
