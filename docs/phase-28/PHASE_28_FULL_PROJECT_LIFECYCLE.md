# Phase 28 — Complete Governed Project Lifecycle

## Status

Phase 28 connects the previously separate AIONEX AIOS capabilities into one durable lifecycle used by a normal authenticated project user.

The lifecycle no longer stops after six-department planning. It performs institutional intake before paid processing, verifies current external facts, creates the governed plan, builds a bounded executable prototype, tests and audits it, evaluates the digital workforce, runs final engineering and release gates, and returns a downloadable evidence package.

## User-visible lifecycle

A project execution progresses through these durable stages:

1. intake;
2. cognitive review by the ten AIOS cognitive cells;
3. constitutional review;
4. independent current research and source verification;
5. wisdom deliberation and strategy ranking;
6. government and council review;
7. ministry routing;
8. controlled provider execution across Architecture, Backend, Frontend, Security, Quality, and DevOps;
9. deterministic implementation generation;
10. implementation tests and rollback verification;
11. workforce assignment, review, performance evaluation, training, and certification;
12. chief engineering review;
13. authorized security review;
14. integration and Definition-of-Done review;
15. final release review;
16. delivery package creation.

The normal user portal displays live stage and progress, provider usage and cost, research status, governance status, workforce results, readiness, blockers, rework, and the final download action.

## Provider and budget boundary

The complete lifecycle uses OpenAI only and has no fallback provider.

Its fixed paid boundary is:

- one controlled web-research Responses request using the fixed `gpt-5.4-nano` research model with exactly one web-search tool call;
- six sequential department planning requests using the configured `gpt-5-mini` model;
- one controlled implementation-specification request with a 3,000-token completion ceiling and no automatic retry;
- maximum combined budget: `0.05 USD` per execution;
- no parallel provider calls;
- no automatic provider fallback;
- provider request and token costs retained in the durable execution record;
- raw prompts, raw responses, credentials, and authorization headers are never returned to users or stored in the public result.

Model availability is checked before paid project work. Planning and implementation remain on the configured `gpt-5-mini` model, while research uses the separately allowlisted web-search-capable `gpt-5.4-nano` model with current fixed pricing. Both use the same external API key, official OpenAI HTTPS endpoints, no fallback, and one combined budget.

## Research and truthfulness

The research stage requires at least two independent HTTPS source domains and at least two attributable verified facts. Every fact must reference an observed source URL. Optional risks, unknowns, and recommended constraints are deduplicated and bounded without inventing placeholder findings when the provider legitimately returns none.

Planning statements such as `tests_passed` or `security_reviewed` are not accepted as executed proof. Release evidence comes only from deterministic tests, retained hashes, the authorized local security review, and rollback verification.

## Executable delivery boundary

Phase 28 creates a tested, self-contained full-stack web prototype with a fixed safe file allowlist, local assets, deterministic browser/server checks, credential scanning, archive hashing, and rollback restoration verification.

The prototype is not misrepresented as an automatically deployed production service. Objectives requiring production hosting, live authentication, payments, native mobile applications, or external integrations remain blocked until their actual infrastructure, credentials, and executed acceptance evidence exist.
Explicit exclusions such as “must not require payments or production deployment” are treated as boundaries, not requested capabilities, so a bounded local prototype is not incorrectly escalated for Owner approval.

## Workforce governance

Every engineering department receives a digital specialist and manager review path. The lifecycle records:

- assignment and review state;
- successful and failed work counts;
- performance, operational health, trust, and learning scores;
- incidents, restrictions, warnings, and recommendation;
- required academy course, assessment score, and certification result;
- active, supervised, retraining, suspended, or retired employment state.

Failed evidence gates trigger supervised rework or retraining rather than silent approval. Results are persisted in the Owner control plane and displayed in `/owner/staff` alongside human identities.

## Package consolidation

Historical runtime modules that were split under the repository-level `aios/` directory are consolidated into the single installable `src/aios/` package. Payments, meetings, notifications, mission control, gateway, distributed runtime, plugins, self-evolution, release candidate, and stable-release modules are now collected by the same installed package and test environment.

Compatibility layers preserve both the modern AIOS kernel interfaces and the retained historical contracts.

## Safety and recovery

- Governance preflight runs before the first paid provider request.
- Every execution ID is immutable and path-contained.
- Completed research, planning, implementation, and full-cycle evidence can be recovered without duplicate paid requests.
- Only one queued or running execution is allowed per project, while completed historical cycles remain available.
- Delivery downloads enforce tenant scope, path containment, symlink rejection, file-count limits, and a 50 MB archive limit.
- Production mutation is not performed by the project cycle.
- Test suites are blocked from using production databases.

## Validation evidence

The Phase 28 branch passed all of the following before PR creation:

- complete root suite: `459 passed`;
- clean Python 3.12 container with only project development dependencies: `459 passed`;
- complete backend suite against fresh isolated PostgreSQL and Redis: `274 passed, 1 skipped`;
- focused project/Owner/language backend contracts: `27 passed`;
- VIP portal integrity, TypeScript, lint, static build, and static smoke: passed;
- VIP static output: `73 pages`, `76 smoke URLs`, six complete locales;
- Owner Dashboard Arabic coverage: `573` translatable UI strings;
- Owner Dashboard TypeScript, selected Owner lint, and production build: passed;
- production Compose validation for both supported definitions: passed;
- Python source compilation and Git whitespace checks: passed.

## Final acceptance requirement

Code completion is not represented as production acceptance until the merged implementation is deployed and one real normal-user project is executed through the complete lifecycle. That acceptance run must preserve the fixed budget, no-fallback rule, production health, tenant isolation, downloadable package, governance evidence, and workforce records.

## Post-execution Owner approval closure

When every executed technical gate passes and the only remaining blocker is `owner approval is required`, the project Organization Owner can explicitly approve the retained evidence package through the tenant-scoped execution API and portal.

The approval path:

- rejects managers, foreign tenants, incomplete executions, and any result with another blocker;
- requires an explicit confirmation after the evidence is available;
- appends a mode-`600` `owner-approval.json` receipt beside the immutable full-cycle manifest instead of rewriting that manifest;
- hashes the retained execution manifest and the approval receipt;
- updates the durable execution, project status, notification, and audit trail;
- adds the approval receipt to the downloadable delivery archive;
- never converts unexecuted external deployment, payment, mobile-store, or third-party integration work into an approved claim.

## Live activation correction

The first post-merge normal-user acceptance attempt reached `external_research` and stopped safely before planning because the research response ended incomplete at the output-token boundary. The failed record stored no raw prompt, raw response, or credential and reported zero completed provider work.

The activation correction assigns web research to the fixed, account-verified `gpt-5.4-nano` model with reasoning disabled and low verbosity, while keeping planning and implementation on `gpt-5-mini`. GPT-5.4 nano is explicitly intended for lightweight extraction and sub-agent work and supports Responses web search and structured outputs. The full worst-case calculation for research, six planning requests, and one implementation request remains below the `0.05 USD` execution cap.
