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
Status: **COMPLETE**

Durable campaign briefs, objectives, market/geography/competitor/audience hypotheses, offers, channels, budget scenarios, confidence/evidence fields, and deterministic simulation output. No provider spend.

### GS-03 — Social account registry + provider capability matrix
Status: **COMPLETE**

Multiple accounts/provider, OAuth state/health metadata, token-expiry model, pause, team assignment, capability matrix, connector simulator. No credentials committed.

### GS-04 — Content operations foundation
Status: **COMPLETE**

Drafts, platform variants, media references, approvals, scheduler, queue, recycle, UTM generation, preview contracts, simulated publishing adapters.

### GS-05 — Analytics & learning ledger
Status: **COMPLETE**

Normalized metrics, experiment/campaign outcomes, failure reason taxonomy, successful-pattern records, recommendations, replay eligibility and anti-repeat rules.

### GS-06 — Lead intelligence & compliant audience data
Status: **COMPLETE**

Source provenance, consent/lawful-basis metadata, dedupe, suppression, retention, imports, provider lead forms, enrichment interface, audience eligibility evaluator. No unauthorized scraping.

### GS-07 — Unified inbox & CRM workflow
Status: **COMPLETE**

Conversations/messages/comments/mentions, read state, assignment, notes, sentiment/spam classification, templates, supported auto-replies with approval/policy constraints, simulated provider events.

### GS-08 — Paid campaign orchestrator (simulation only)
Status: **COMPLETE**

Campaign/ad-set/ad/creative lifecycle, budget/day caps, approvals, stop-loss rules, A/B experiments, launch simulation, pause/scale/replay decisions. `real_spend_allowed=false` hard gate.

### GS-09 — First live provider connectors
Status: **META_OWNED_READ_ONLY_VERIFIED_EXTERNAL_GATES_REMAIN**

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


### GS-02 implementation checkpoint — 2026-08-14
- Worktree: `feature/gs02-campaign-intelligence`.
- Build started only after GS-01 closeout was merged and production ingress verified.
- Scope: durable campaign intelligence + deterministic simulation only; no external ad-platform credentials and no real spend.
- Access gates: `campaign.research` and `campaign.simulation` from GS-01.
- Hard safety invariant: `real_spend_allowed=false`.
- Core deterministic simulation tests: 13/13 PASS after tightening weak-hypothesis detection.
- Root completion + public-ingress contracts: 16/16 PASS.
- Isolated PostgreSQL migration upgraded through `20260814_0017`; durable brief + expected simulation committed and re-read successfully.
- Durable simulation evidence: confidence `0.858`; `real_spend_allowed=false` persisted both as a column and inside result payload.
- No external advertising provider, OAuth credential, audience upload, message sending, publishing, or spend occurred.
- CI Backend Tests exposed a stale Alembic-head expectation (`20260810_0016`); the contract was updated to shipped head `20260814_0017`, and the affected database + GS-02 tests passed 8/8.
- CI/core regression found: zero-dead audit rejected a bare `pass` in `GrowthCampaignError`; replaced with a documented exception body.
- Full root core suite after fix: 675/675 PASS.
- PR #314 merged to `main` as `881fe85503db05b944f211dba4d59af800f831f7` after all GitHub production gates passed.
- Production migration verified at Alembic head `20260814_0017`; Backend and Nginx healthy.
- Public ingress verification: `/api/v1/growth-social/campaigns/briefs` returns HTTP 401 from Backend when unauthenticated, proving the Nginx allowlist reaches the application.
- Live production simulation with a temporary isolated tenant/user and owner-granted `campaign.research` + `campaign.simulation` completed successfully with confidence `0.905`, reason codes `simulation-only,no-provider-spend`, and `real_spend_allowed=false`; all temporary records were deleted and cleanup verified.
- GS-02 accepted. Next batch: **GS-03 — Social account registry + provider capability matrix**.


### GS-03 implementation checkpoint — 2026-08-14
- Worktree: `feature/gs03-social-account-registry`.
- Started only after GS-02 closeout PR #315 merged and `main` returned clean.
- Managed social accounts are separate from authentication `ExternalIdentity` records.
- No provider access/refresh token may be stored in the database, logs, repository, API responses, or tests; only opaque external secret references are permitted.
- Provider capability states remain declarative `unverified`/`simulated` until GS-09 live connector validation; GS-03 makes no claim of live provider API support.
- Scope: multiple accounts per provider, health/expiry/pause, team assignment, capability matrix, and deterministic connector simulation.
- No external provider mutation, publishing, messaging, scraping, or advertising spend in GS-03.
- Durable models/migration `20260814_0018` added for managed social accounts and provider capability verification states.
- User API surface added for provider matrix, multiple-account registry, pause/resume, disconnect, team assignment, health simulation, and capability simulation.
- Public API responses expose only `credential_configured`; raw credential references are never returned.
- Isolated PostgreSQL migration upgraded cleanly through `20260814_0018`.
- Focused GS-03 + Alembic-head tests: 12/12 PASS.
- Root completion/ingress/roadmap contracts: 18/18 PASS; full root Core suite: 676/676 PASS.
- CI-equivalent static quality: Ruff PASS and Mypy PASS across 150 backend source files.
- Durable integration proved two managed accounts for the same provider, team assignment, pause/resume, 7-day expiry health warning, disconnect with credential-reference clearing, and deterministic capability simulation.
- Capability simulation can move only `unverified -> simulated`; no GS-03 path can create `verified`, and every simulated result reports `live_verified=false` and `live_provider_call=false`.
- All registry mutations added in GS-03 are audited.
- PR #316 merged to `main` as `69f1f5e71c9c0a25b97d953797261fa88cfa6585` after every GitHub production gate passed.
- Production migration verified at Alembic head `20260814_0018`; Backend and Nginx healthy after rollout/remount.
- Public ingress verification: `/api/v1/growth-social/accounts` and `/api/v1/growth-social/providers/capabilities` both return HTTP 401 from Backend when unauthenticated, proving the Nginx allowlist reaches the application.
- Live production acceptance with a temporary isolated tenant/user proved two managed accounts on the same provider, team assignment, 7-day expiry health warning, pause/resume, and deterministic `content.publish` capability simulation.
- Live acceptance explicitly reported `live_verified=false`, `live_provider_call=false`, and `credential_value_exposed=false`; the temporary tenant/account/audit fixtures were removed and cleanup verified.
- Production capability matrix baseline now contains 88 rows (11 providers x 8 declarative capabilities): `unverified=88`, `simulated=0`, `verified=0`. Live verification remains reserved for GS-09.
- GS-03 accepted. Next batch: **GS-04 — Content operations foundation**.


### GS-04 implementation checkpoint — 2026-08-14
- Worktree: `feature/gs04-content-operations`.
- Started only after GS-03 closeout PR #317 merged and `main` returned clean.
- Access gate: GS-01 `content.publish`; owner deny/approval requirements remain authoritative.
- Scope: drafts, provider/account variants, opaque media references, approval workflow, scheduler/priority queue, recycle, deterministic UTM generation, provider-neutral previews, and simulated publishing adapters.
- No provider network call, live post creation/edit/delete, DM, comment reply, media upload, scraping, or advertising spend in GS-04.
- Hard invariant: `live_publish_allowed=false`.
- Durable models/migration `20260814_0019` added for content items, provider/account variants, schedules/priority queue, and publish simulations.
- Deterministic content engine includes opaque media refs, UTM generation, provider-neutral preview, approval invalidation after edits, recurrence/recycle, cancellation, and simulated due-queue processing.
- Owner-controlled `content.publish` access is re-read for every operation; `approval_required` from GS-01 blocks scheduling until an Owner/Admin/Super Owner approves.
- CI-equivalent static quality: Ruff PASS and Mypy PASS across 152 backend source files.
- Isolated PostgreSQL migration upgraded cleanly through `20260814_0019`.
- Focused GS-04/Alembic/route-quality tests: 10/10 PASS; root completion/ingress/roadmap contracts: 19/19 PASS; full root Core suite: 677/677 PASS.
- Durable acceptance proves Draft -> Variant -> Preview/UTM -> Approval -> Priority Schedule -> simulated publish -> daily recurrence -> manual recycle, plus approval reset after edit and blocked simulation when the target account is paused.
- Every simulation records `simulation-only`, `no-provider-call`, `live-publish-disabled`; no path in GS-04 can set `live_publish_allowed=true`.
- PR #318 merged to `main` as `5ae52bd37267d0fe5d86758fac335c06cc9226aa` after every GitHub production gate passed.
- Production migration verified at Alembic head `20260814_0019`; Backend and Nginx healthy.
- Public ingress verification: `/api/v1/growth-social/content` and `/api/v1/growth-social/content/queue` both return HTTP 401 from Backend when unauthenticated.
- Live production acceptance with an isolated temporary tenant/social account proved approval enforcement, deterministic preview/UTM, priority schedule, simulated publish success, daily recurrence, and manual recycle.
- Live acceptance explicitly reported `live_publish_allowed=false`, `live_provider_call=false`; all temporary records were removed and cleanup verified.
- Provider capability matrix was restored after acceptance to the GS-03 baseline: `verified=0`, `simulated=0`, `unverified=88`.
- GS-04 accepted. Next batch: **GS-05 — Analytics & learning ledger**.


### GS-05 implementation checkpoint — 2026-08-14
- Worktree: `feature/gs05-analytics-learning`.
- Started only after GS-04 closeout PR #319 merged and `main` returned clean.
- Access gate: GS-01 `analytics.read`; owner deny remains authoritative.
- Scope: normalized observations, deterministic outcome classification, failure-reason taxonomy, success/failure pattern ledger, evidence-bound recommendations, replay eligibility, and repeated-failure anti-repeat blocking.
- No provider analytics fetch, campaign mutation, live replay, budget change, or external network call in GS-05.
- Recommendations are advisory only; `auto_optimization_allowed=false` and `auto_replay_allowed=false`.
- Durable models/migration `20260814_0020` added for normalized performance observations, learning entries, and optimization recommendations.
- Deterministic normalization calculates CTR, engagement rate, conversion rate, CPC, CPA, and ROAS from non-negative input metrics; context/evidence reject sensitive credential fields.
- Failure taxonomy and target-aware classifier produce `success`, `failure`, or `inconclusive` with explainable reason codes.
- Pattern fingerprints remember successful/failing conditions; a successful evidence-rich pattern becomes `replay_candidate` only, first failure becomes `iterate`, and the same failure repeated twice becomes `avoid` with `repeat-failure-blocked`.
- Analysis is idempotent per observation; successful/failure counts and pattern summaries are durable.
- `auto_optimization_allowed=false` and `auto_replay_allowed=false` are persisted on every recommendation; GS-05 cannot mutate campaigns or replay content.
- CI-equivalent static quality: Ruff PASS and Mypy PASS across 154 backend source files.
- Isolated PostgreSQL migration upgraded cleanly through `20260814_0020`.
- Focused GS-05/Alembic/route-quality tests: 9/9 PASS; root completion/ingress/roadmap contracts: 20/20 PASS; full root Core suite: 678/678 PASS.


### GS-05 production closeout — 2026-08-14
- PR #320 merged to `main` as `bab408053732bb6f75c0dcf50f3f5272344115e6` after every GitHub production gate passed.
- Production migration verified at Alembic head `20260814_0020`; Backend and Nginx healthy.
- Public ingress verification: `/api/v1/growth-social/analytics/observations` and `/api/v1/growth-social/analytics/recommendations` return HTTP 401 from Backend when unauthenticated.
- Live production acceptance with an isolated temporary tenant proved evidence-backed success -> `replay_candidate`, first failure -> `iterate`, and repeated identical failure -> `avoid` with `repeat-failure-blocked`.
- `auto_replay_allowed=false` and `auto_optimization_allowed=false` were confirmed in live acceptance; no provider call or live campaign mutation occurred.
- All temporary acceptance records were removed and cleanup verified.
- GS-05 accepted. Next batch: **GS-06 — Lead intelligence & compliant audience data**.


### GS-06 implementation checkpoint — 2026-08-14
- Worktree: `feature/gs06-lead-intelligence`.
- Scope: provenance, consent/lawful basis, suppression, dedupe, retention and audience eligibility only.
- No unauthorized scraping, no outbound messaging, no audience upload, and no live provider call.
- Access gate: `leads.manage` from GS-01; owner deny remains authoritative.
- Static quality: Ruff PASS; Mypy PASS across 156 backend source files with CI-equivalent PYTHONPATH.
- Isolated PostgreSQL migration upgraded cleanly through `20260814_0021` after making GS-06 migration idempotent for fresh databases where the consolidated initial schema already materializes current Base metadata; partial presence fails closed.
- Focused GS-06 + Alembic-head tests: 4/4 PASS; root completion/ingress/roadmap contracts: 21/21 PASS.
- Full root suite inside the backend test image is not CI-equivalent for older deployment/runtime tests because the image lacks host executables and importable test-package/runtime surfaces; those environmental failures are deferred to the official GitHub Core/Backend gates and are not treated as GS-06 regressions.


### GS-06 production closeout — 2026-08-14
- PR #322 merged to `main` as `d06780c9782b8a889e8859592dd4d56193375b68` after every GitHub production gate passed, including Backend, Core, CodeQL, SBOM, Browser, Production Docker, DB-upgrade preservation and backup/restore smoke.
- Production migration verified at Alembic head `20260814_0021`; Backend and Nginx healthy.
- Public ingress verification: `/api/v1/growth-social/leads` returns HTTP 401 from Backend when unauthenticated.
- Live production acceptance used an isolated temporary tenant and an owner-granted `leads.manage` override to prove owner-controlled feature access.
- Acceptance proved deterministic dedupe of the same lead across two authorized provenance sources, active lawful-basis eligibility, immediate suppression/opt-out blocking, and retention-expiry blocking.
- Safety invariants confirmed live: `unauthorized_scraping_allowed=false`, `outbound_outreach_allowed=false`, `live_audience_upload_allowed=false`, and `live_provider_call=false`.
- All temporary tenant, lead, provenance, consent, suppression, billing, access-override and audit fixtures were removed; cleanup verified.
- GS-06 accepted. Next batch: **GS-07 — Unified Inbox & CRM workflow foundation**.


### GS-07 execution start — 2026-08-14
- Worktree: `feature/gs07-unified-inbox` from clean `origin/main`.
- Scope: durable normalized inbox threads/messages, read/unread, star, assignment, internal notes, quick-reply drafts, search/filter, CRM lead linking, sentiment/spam tags and deterministic inbound simulation.
- Access capability: `inbox.manage`, resolved through existing owner-controlled Growth Social access policy.
- Safety boundary: no external send, block, mute, moderation action, webhook/provider mutation or live provider call in GS-07.


### GS-07 pre-merge validation — 2026-08-14
- Durable schema added for normalized inbox threads, messages, internal notes and quick-reply drafts; migration `20260814_0022` upgrades successfully from a fresh isolated PostgreSQL database.
- Owner-controlled capability: `inbox.manage`; live external actions remain disabled.
- Static quality: Ruff PASS and Mypy PASS across 158 backend source files.
- Focused GS-07 workflow + Alembic head tests: 4/4 PASS.
- Root completion/ingress/roadmap contracts: 21/21 PASS after registering `growth_inbox` in `ENDPOINT_BATCH`.
- Safety invariants: live provider calls, external sends, block, mute and moderation actions are all disabled in GS-07.

### GS-07 production closeout — 2026-08-14
- PR #324 merged to `main` as `a0a5aeddb810d0338b21f2bfb06f9baa758effb5` after every GitHub production gate passed, including Backend, Core, CodeQL, SBOM, Browser boundaries, Production Docker, DB-upgrade preservation, legacy `.env`, and backup/restore smoke.
- Production migration verified at Alembic head `20260814_0022`; Backend healthy.
- Nginx was force-recreated to remount the updated public allowlist; `/api/v1/growth-social/inbox` then returned HTTP 401 from Backend when unauthenticated, proving the public ingress reaches the authenticated application route.
- Live production acceptance used an isolated temporary tenant plus an owner-granted `inbox.manage` override and no external provider credentials.
- Acceptance proved deterministic simulated inbound normalization and dedupe, CRM lead linking, read/star/assignment/internal-note workflow, and quick-reply generation as an approval-required draft only.
- Safety invariants confirmed live: `external_send_allowed=false`, `live_provider_call=false`, `live_block_allowed=false`, `live_mute_allowed=false`, and `live_moderation_allowed=false`.
- All temporary tenant, lead, thread, message, note, draft, billing, access-override and audit fixtures were removed; cleanup verified.
- GS-07 accepted. Next batch: **GS-08 — Paid campaign orchestrator (simulation only)**.

### GS-08 execution start — 2026-08-14
- Worktree: `feature/gs08-paid-campaign-simulation` from clean `origin/main`.
- Scope: durable campaign/ad-set/ad/creative lifecycle, hard budget/day caps, approval gates, stop-loss policy, deterministic A/B experiment allocation, launch simulation, and explainable pause/scale/replay/hold decisions.
- Access capability: `ads.manage`, resolved through the existing owner-controlled Growth Social access policy; owner approval remains authoritative.
- Safety boundary: `real_spend_allowed=false`, `live_provider_call=false`, `live_campaign_mutation=false`, and `automatic_budget_increase_allowed=false` throughout GS-08. No provider credential or real advertising spend is used.


### GS-08 local acceptance checkpoint — 2026-08-14
- Durable GS-08 schema added for paid campaign, ad set, creative, ad, experiment, launch simulation and decision ledger; Alembic head advanced to `20260814_0023`.
- Static quality: Ruff clean on GS-08 files; Mypy PASS across 160 Backend source files using the project root `PYTHONPATH`.
- Isolated PostgreSQL migration from zero through `20260814_0023`: PASS.
- Focused GS-08 workflow + Alembic head contract: 3/3 PASS.
- Root completion/public-ingress/Growth-Social roadmap contracts: 21/21 PASS.
- Acceptance proves owner-controlled `ads.manage`, hard total/daily budget caps, campaign approval before simulation, deterministic A/B allocation and launch simulation, stop-loss/hold/scale/iterate decision ledger, with `real_spend_allowed=false`, `live_provider_call=false`, `live_campaign_mutation=false`, `automatic_budget_increase_allowed=false`, and `automatic_execution_allowed=false`.

### GS-08 production closeout — 2026-08-14
- PR #326 merged to `main` as `47e659bad98e583ccf80448b14cac6198b2dafb3` after every GitHub production gate passed, including Backend, Core, CodeQL, SBOM, Browser boundaries, Production Docker, DB-upgrade preservation, legacy `.env`, and backup/restore smoke.
- Production migration verified at Alembic head `20260814_0023`; Backend healthy.
- Nginx was force-recreated to remount the updated public allowlist; `/api/v1/growth-social/paid-campaigns` returned HTTP 401 from Backend when unauthenticated, proving the authenticated application route is reachable.
- Live production acceptance used an isolated temporary tenant plus an owner-granted `ads.manage` override and no provider credentials.
- Acceptance proved campaign approval is mandatory before simulation, hard total/daily budget caps, deterministic A/B allocation and repeatable launch simulation, and an explainable `scale_candidate` decision that remains manual-only.
- Safety invariants confirmed live: `real_spend_allowed=false`, `live_provider_call=false`, `live_campaign_mutation=false`, `automatic_budget_increase_allowed=false`, and `automatic_execution_allowed=false`. No real advertising spend or provider mutation occurred.
- All temporary campaign/ad-set/creative/ad/experiment/simulation/decision/billing/access-override/user/organization/audit fixtures were removed; cleanup verified.
- GS-08 accepted. Next batch: **GS-09 — First live provider connectors**, subject to provider credentials/app approvals and no-spend/read-only or sandbox validation before any mutation.


### GS-09 execution start — 2026-08-14
- Worktree: `feature/gs09-provider-connectors` from clean `origin/main`.
- Scope now: provider connector framework, adapter contracts, capability verification state machine, read-only/sandbox validation harness, credential-reference handling, provider health probes, and audit evidence.
- Live activation remains gated: no raw credentials in Git/DB/logs, no provider mutation, no real spend, no external publish/send, and no capability may become `live_verified` without owner credentials/app approval plus a successful provider-specific validation.
- First provider adapters will remain `configured=false` / `verification_state=unverified` unless real provider credentials and approvals are supplied later.


### GS-09 safe-framework validation — 2026-08-14
- Provider connector catalog/framework implemented for supported Growth Social providers.
- Raw credential material is rejected; only opaque credential references are accepted by contract.
- Live write/spend/publish/send modes are fail-closed. Contract validation performs zero provider calls and never marks a capability live-verified.
- Read-only/sandbox validation can become `*_ready` only when a credential reference and platform approval are both present; even then mutation/spend remain disabled until provider-specific external validation occurs.
- Static quality: Mypy PASS across 162 backend files; focused connector tests 4/4 PASS; completion/public-ingress/Growth Social roadmap contracts 21/21 PASS.
- External gate remains: actual read-only/sandbox provider validation requires owner-supplied credential references and provider app/account approval. No raw secrets are to be entered into chat, Git, DB payloads, or logs.


### GS-09 safe-framework production closeout — 2026-08-14
- PR #328 merged to `main` as `db15bf3cedce34601159a6402d3af08b2f2bbce2` after every GitHub production gate passed, including Backend, Core, CodeQL, SBOM, Browser boundaries, Production Docker, DB-upgrade preservation, legacy `.env`, and backup/restore smoke.
- Production Backend rebuilt from `main` and returned healthy. No schema migration was required for the GS-09 safe framework.
- Nginx was force-recreated to remount the updated public allowlist; `/api/v1/growth-social/provider-connectors/catalog` returned HTTP 401 from Backend when unauthenticated, proving the authenticated application route is reachable.
- Safe production acceptance executed against production code with zero provider credentials and zero external provider calls.
- Acceptance proved 11 provider descriptors are registered; raw credential-like values are rejected; contract validation remains `unverified` and performs no provider call; live mutation/spend modes are fail-closed; read-only readiness still requires an opaque credential reference plus platform approval; mutation/spend remain disabled.
- Acceptance evidence: `GS09_SAFE_PRODUCTION_ACCEPTANCE_OK`, `contract_provider_call_allowed=false`, `contract_verification_state=unverified`, `raw_credentials_rejected=true`, `live_mutation_modes_rejected=true`, `mutation_allowed=false`, `spend_allowed=false`.
- Internal GS-09 framework work is complete. External gate now blocks only provider-specific read-only/sandbox validation: owner-supplied credential references installed securely on the server plus provider app/account approval. Raw secrets must not be pasted into chat, Git, database payloads, or logs.


### GS-09 Meta sandbox validation checkpoint — 2026-08-15
- Meta Marketing API app `AIONEX-AIOS` configured in development access with `ads_read` available for testing.
- Sandbox ad account `AIONEX-AIOS Sandbox` created with AED currency and Asia/Dubai timezone; no real spend occurred.
- User token and sandbox token are stored outside the repository under root-only files; raw token values were never added to Git, database payloads, logs, or chat.
- Direct server-side read-only verification against Meta Graph/Marketing API v26.0 succeeded for the sandbox account (`META_SANDBOX_READ_OK`), confirming account name, AED currency, Asia/Dubai timezone, and active account status.
- The Meta sandbox token is mounted into the production Backend only through an operations override outside Git; the repository Compose file remains unchanged from `origin/main`.
- Added internal `growth_meta_connector` adapter for Meta sandbox `ads_read` validation. The adapter reads only an allowlisted secret-file path, calls only the sandbox ad-account GET endpoint, redacts provider errors, never persists raw token material, and hard-codes mutation/spend evidence to false.
- Added unit coverage for read-only request shape, token redaction, secret-path allowlist, invalid account IDs, and malformed API versions. Focused Meta tests: 4/4 PASS; Black/Ruff PASS; adapter Mypy PASS.
- After PR/CI/merge, deployment will use the external operations override to run the validation from inside AIOS and persist `meta/ads_read = sandbox_verified`; no ad creation, budget change, publish/send, or real spend is permitted.
- PR #330 CI/Core regression exposed a zero-dead `bare-pass` finding in Meta HTTP-error parsing; replaced with explicit fallback to the HTTP status code.
- Full root Core suite after the fix: 679/679 PASS.


### GS-09 Meta sandbox production validation closeout — 2026-08-15
- PR #330 passed every required GitHub production gate after one zero-dead audit fix; full root Core suite after the fix: 679/679 PASS.
- PR #330 merged to `main` as `73060bf6630409f9789fdb2192ebd4f550e6bb52`.
- Production Backend rebuilt from merged `main` with the Meta operations override stored outside Git under `/opt/aionex-ops/`; the repository Compose file remains free of the Meta token mount.
- Meta sandbox token remains in a root-owned mode-0600 host file outside the repository and is mounted read-only into the Backend. Raw token material is not stored in Git, database payloads, report evidence, or application logs.
- Live validation executed from inside the production AIOS Backend using Meta Marketing API / Graph API v26.0 against the sandbox ad account only.
- Validation result: `AIOS_META_SANDBOX_VALIDATION_OK`, provider `meta`, capability `ads_read`, verification state `sandbox_verified`, account `AIONEX-AIOS Sandbox`, currency `AED`, timezone `Asia/Dubai`, account status `1`.
- Safety evidence confirmed live: `provider_call_allowed=true` for the read-only sandbox GET only, `mutation_allowed=false`, `spend_allowed=false`, `raw_secret_persisted=false`.
- Durable database verification confirmed `meta/ads_read = sandbox_verified`, credential reference `secretref://file/meta/marketing-api-sandbox-token`, `raw_secret_persisted=False`, `mutation_allowed=False`, and `spend_allowed=False`.
- No ad creation, budget edit, publish/send, audience upload, account mutation, or real advertising spend occurred.
- Meta sandbox read-only validation is complete. GS-09 remains externally gated for additional provider-specific validations and for any Meta production/live-write capability beyond this sandbox-read boundary.


### GS-09 Meta owned-assets read-only implementation checkpoint — 2026-08-15
- Added a separate internal Meta owned-assets `ads_read` validator using the existing general Meta token stored outside Git in a root-only mode-0600 host file.
- Operations wiring remains outside the repository in `/opt/aionex-ops/meta-owned-readonly-compose.override.yml`; repository Compose remains unchanged.
- The validator requests only `/me/adaccounts?fields=id,account_status&limit=100` on Meta Graph API v26.0 and never requests names, campaign data, budgets, creatives, audiences, or write scopes.
- Durable evidence is identity-minimized: only account count, active-account count, truncation flag, API version, scope=`owned_assets`, and safety flags are recorded. Account IDs, account names, paging URLs, raw token material, and provider response bodies are not persisted or printed.
- Hard invariants: `provider_call_allowed=true` only for the read-only GET; `mutation_allowed=false`; `spend_allowed=false`; credential stored only as opaque `secretref://file/meta/marketing-api-token`.
- Static quality: Black PASS, Ruff PASS, adapter Mypy PASS; focused owned-assets tests 4/4 PASS; full root Core suite 679/679 PASS.
- After PR/CI/merge, production validation will run from inside AIOS using the external operations override and, if successful, promote `meta/ads_read` to `read_only_verified` for scope `owned_assets` while preserving the prior sandbox evidence.


### GS-09 Meta owned-assets production read-only closeout — 2026-08-15
- PR #332 passed every required GitHub production gate and merged to `main` as `f73391f97c1f7253f64ca8eef59c541bd8f63231`.
- Production Backend rebuilt from merged `main` using both Meta operations overrides stored outside Git; repository Compose remains free of Meta token mounts.
- Meta general token remains outside the repository in a root-owned mode-0600 host file and is mounted read-only only for the production validation process. Raw token material is not stored in Git, database payloads, report evidence, or logs.
- Live validation executed from inside the production AIOS Backend using Meta Graph API v26.0 against `/me/adaccounts?fields=id,account_status&limit=100` only.
- Validation result: `AIOS_META_OWNED_READ_ONLY_VALIDATION_OK`, provider `meta`, capability `ads_read`, scope `owned_assets`, verification state `read_only_verified`, 2 accessible ad accounts, 1 active account, and no pagination truncation.
- Identity minimization confirmed: account names, account IDs, paging URLs, campaign details, budgets, creatives, audiences, and provider response bodies are not persisted or printed by the validator.
- Durable database verification confirmed `meta/ads_read = read_only_verified`; prior `gs09_meta_sandbox` evidence remains preserved; owned credential reference is `secretref://file/meta/marketing-api-token`; `raw_secret_persisted=False`; `mutation_allowed=False`; `spend_allowed=False`.
- No ad creation, campaign mutation, budget edit, audience upload, publish/send, or real advertising spend occurred.
- Meta owned-assets read-only validation is complete. GS-09 remains externally gated only for broader Meta third-party/business access, any Meta live-write capability, and additional provider-specific validations.
