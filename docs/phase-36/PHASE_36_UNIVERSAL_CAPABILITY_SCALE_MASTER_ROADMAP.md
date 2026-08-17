# Phase 36 — Universal Capability, Creative Media & 1000+ User Scale Master Roadmap

Status: **AUTHORITATIVE NEW PRODUCT EXPANSION CONTRACT — implementation not complete until every Phase 36 batch is closed.**

Date opened: 2026-08-17.

## 1. Owner directive and scope expansion

The Owner has expanded the AIONEX AIOS product contract beyond the previously closed Phase 29/35 scope.

AIONEX AIOS is not a single-user project generator and is not a single-feature application. The target product is a general governed operating platform that can accept legal/buildable ideas across software, media, design, audio, video, music, education, healthcare/professional assistance, commerce, institutions and government workflows, then compose the required capabilities without replying that a normal project family has no builder.

The Owner states that the company is licensed/authorized to develop software and media products across the requested categories. AIOS must therefore not reject an otherwise lawful/buildable product merely because the internal catalog lacks a hand-written product template. External platform credentials, store signing, third-party provider terms, sector-specific certification, data residency, physical-device validation or other outside operational authority remain explicit activation gates when they are actually required; they are not `unsupported builder` states.

This expansion supersedes any interpretation that the product is final merely because the historical Phase 29 completion contract was closed. Phase 29 remains valid evidence for its historical scope; **final product completeness under the Owner's current scope requires Phase 36 to close.**

## 2. Non-negotiable product principles

1. **No global single-user execution bottleneck.** A production singleton worker may exist only as a temporary deployment profile; it is not the final architecture.
2. **1000 concurrent users is the minimum platform design target, not the ceiling.** The architecture must scale horizontally beyond 1000 by adding API, CPU, GPU, render and realtime nodes without redesigning tenant or workflow semantics.
3. **No cross-tenant state leakage.** Users may share physical model/provider infrastructure, but prompts, artifacts, credentials, execution state, memory and evidence remain tenant/project scoped.
4. **No normal legal/buildable project family is rejected because “AIOS has no builder”.** The Universal Capability Composer must decompose the request into capabilities/targets and exact external activation gates.
5. **No false completion.** A capability is reported using explicit maturity states: `specified`, `source_built`, `locally_executed`, `provider_connected`, `runtime_verified`, `scaled`, `production_ready`.
6. **Provider/model claims are never execution proof.** Generated media/source must have retained runtime/build/render evidence where applicable.
7. **Resource-aware execution.** Lightweight API work, CPU builds, GPU image/video/3D work, realtime media and long-running jobs are separate resource classes with independent worker pools, quotas and backpressure.
8. **Latest stable technology review is mandatory at the start of every batch.** The selected versions must be recorded from official upstream sources before implementation; stale pins must be justified or upgraded.
9. **Security is part of the builder.** Generated or processed artifacts use least privilege, isolated workers, secret references, read-only inputs where possible, bounded outputs, provenance, checksums and fail-closed validation.
10. **Every change is documented.** No batch, update, feature, production fix or discovered problem may close without an entry in this roadmap/reporting system.

## 3. Mandatory reporting and incident/change ledger protocol

This file is the live source of truth for Phase 36. Every Phase 36 PR must update it before merge.

### Before each batch

Record:
- batch objective and exact product/user behavior;
- current production state and known gap;
- files/services/data schemas expected to change;
- technology/version review and official upstream sources;
- security/privacy/cost/licensing/sector risks;
- acceptance criteria, load targets and rollback plan.

### During implementation

Every material problem must be logged, including problems found during development, CI, deployment or user acceptance. An incident/problem entry must contain:
- entry ID, date/time and batch;
- environment and affected component;
- visible symptom and user impact;
- how it was detected and exact reproduction evidence;
- root cause, not only the error message;
- why the existing test/architecture did not prevent it;
- code/config/data fix;
- security and tenant-isolation review;
- regression test added;
- rollout/rollback result;
- residual risk or follow-up, if any.

A problem that is fixed but not documented is **not closed**.

### After each batch

Record:
- final changed paths and schemas;
- tests and exact pass counts;
- performance/load evidence;
- security/SBOM/dependency evidence;
- PR number, merge SHA and protected checks;
- backup/deployment procedure and live acceptance;
- before/after metrics;
- any external activation gate still open;
- next batch.

### CI enforcement target

Batch 36A must add a changed-surface/report-receipt check so future product PRs that touch Phase 36-owned code cannot silently merge without a Phase 36 report update or an explicit documented exemption.

## 4. Minimum 1000-concurrent-user definition

“1000 users at the same time” is defined as a platform property, not as forcing 1000 GPU renders onto one physical server.

The minimum acceptance target is:

- at least **1000 concurrently authenticated active users** in the load profile;
- at least **1000 simultaneous/near-simultaneous job submissions** accepted with tenant isolation and idempotency;
- at least **1000 independent active workflow records** able to remain in-flight without a global singleton execution lock;
- project/studio jobs may be queued by resource class, but different ready jobs must execute in parallel whenever worker capacity exists;
- no lost job, duplicate terminal execution, cross-tenant artifact, stale-lease double completion or queue corruption;
- graceful backpressure instead of overload collapse;
- horizontal worker/node addition must increase throughput without data migration or redesign;
- failover/recovery must preserve leases/fencing and reject stale completions;
- performance tests must include HTTP, authenticated user flows, queue admission, WebSocket/realtime paths where applicable and artifact upload/download;
- the load generator must not be the bottleneck; distributed k6 execution is used when necessary.

Initial target SLOs to be measured and adjusted only with evidence:
- API/read p95 <= 500 ms for ordinary lightweight reads under the 1000-user profile;
- durable job enqueue p95 <= 1 s;
- HTTP error rate < 0.5% excluding deliberate policy/rate-limit responses;
- zero tenant-isolation violations and zero lost/duplicate jobs;
- recovery from one worker/node loss without losing accepted durable work.

Heavy GPU/render stages have separate capacity SLOs. The platform must admit and safely schedule the 1000-user workload; physical simultaneous GPU render count is determined by available GPU nodes and provider rate limits and scales horizontally.

## 5. Scale architecture

The existing Phase 23 distributed execution fabric and Phase 24A/24B multi-node/multi-host runtime are the foundation. Phase 36 must connect the **live user Project Execution path** to them instead of creating a second scheduling system.

Target flow:

`User/API -> Admission & Tenant Policy -> Durable Workflow/Task Graph -> Capability Scheduler -> Resource-Class Queue -> Worker Pool -> Artifact/Result Store -> Verification -> Governance/Release`

### Worker/resource pools

- `project-planning`: research, analysis, department planning, governance inputs;
- `project-build-cpu`: source generation, compile/build/test, packaging;
- `security`: SAST/SCA/SBOM/security verification;
- `image-design-gpu`;
- `video-render-gpu`;
- `audio-music`;
- `three-d-xr-gpu`;
- `realtime-media`;
- `data-etl`;
- `sector-specialist`;
- `provider-adapter` workers for bounded third-party calls.

Every pool declares capabilities, capacity, current load, health and cost class. Scheduling uses capability matching, weighted fairness, per-tenant quotas, priority, backpressure, leases, fencing, retries and DLQ.

### Deployment profiles

- **Single-host profile:** current Docker Compose remains suitable for development/early production and may run a small number of worker replicas.
- **Scale profile:** Kubernetes-compatible deployment with stateless API replicas, horizontally scaled worker deployments, CPU/GPU node pools, NetworkPolicies, Pod Security restricted posture, secrets mounted by reference and autoscaling from queue/resource metrics.
- **Multi-host AIOS runtime:** existing TLS/HMAC Phase 24 contracts remain valid and are integrated rather than discarded.

The scale profile must not make Kubernetes a hard dependency for local development.

## 6. Current technology-refresh snapshot

This is a planning snapshot, not a permanent pin. Every batch rechecks official upstream sources.

- Kubernetes active line reviewed on 2026-08-17: `1.36.x`; official release/download pages currently publish `1.36.2` as the latest available patch in that line.
- OpenTelemetry Collector official documentation currently references release `v0.157.0`; Phase 36 uses OpenTelemetry for traces/metrics/log correlation and horizontally scalable collector patterns.
- FFmpeg official stable release reviewed on 2026-08-17: `8.1.2`; Phase 36 media render/transcode contracts target an FFmpeg 8.1-compatible pipeline unless a later stable release is selected at implementation time.
- Grafana k6 is the load-test baseline. Official k6 guidance states a properly resourced single instance can exceed the 1000-VU requirement and supports distributed execution; Phase 36 still validates the load generator separately from the system under test.
- Existing Universal Builder pins (Next/React/Expo/Tauri/FastAPI/Python/Rust/Solidity) remain subject to per-batch official-source revalidation.

Official reference entry points:
- `https://kubernetes.io/releases/`
- `https://opentelemetry.io/docs/collector/`
- `https://ffmpeg.org/download.html`
- `https://grafana.com/docs/k6/latest/testing-guides/running-large-tests/`

## 7. Universal product capability taxonomy

The following are first-class required product capabilities, not optional future ideas.

### Software and application engineering
- websites, PWAs, SaaS, portals;
- REST/GraphQL/WebSocket APIs and serverless;
- Android/iOS, desktop and browser extensions;
- databases, analytics, ETL/data pipelines;
- bots, automation, CLIs, SDKs/libraries;
- commerce, subscriptions, billing boundaries;
- IoT/firmware simulation, robotics, smart contracts;
- realtime chat, voice/video, streaming and conferencing.

### Creative image/design
- logo creation and logo systems;
- brand kits, posters, social creatives and advertising designs;
- raster/vector output, resizing, background operations, variants;
- infographics, diagrams, atypical/experimental graphics;
- prompt generation/refinement and reusable prompt packs;
- editable source plus final export profiles.

### Video/cinema/motion
- text-to-video, image-to-video and logo-to-video workflows;
- short and long-form advertising video;
- multi-scene storyboard, continuity, camera/shot language and scene DAG;
- 2D animation, 3D animation, motion graphics, kinetic typography;
- infographic animation, compositing, transitions, VFX/effects and subtitles;
- product videos, explainers, intros/outros, social/video-ad presets;
- resumable scene rendering and final assembly;
- output profiles including common web/broadcast containers/codecs and high-resolution 1080p/1440p/4K, with higher resolutions when source/model/hardware supports them.

The competitive capability benchmark is the *class* of workflows seen in tools such as Renderforest, PixVerse, Risha.ai and Pixaflow. AIOS must provide equivalent categories through its own governed workflow and must not copy proprietary templates/assets.

### Audio/voice/music
- text-to-speech and speech-to-text;
- dubbing/localization and timing alignment;
- voice transformation with consent/identity evidence where required;
- diarization, cleanup, noise reduction and mastering;
- sound effects and audio scene design;
- song concept, lyrics, melody/arrangement, instrumental generation, vocals, stems, mix and master;
- jingles, podcasts, narration and multi-speaker productions;
- exports such as WAV/FLAC/MP3/AAC/Opus according to the selected production profile.

### 2D/3D/XR/interactive graphics
- 2D canvas/game/animation;
- Three.js/WebGL and real 3D asset workflows;
- GLB/GLTF and governed additional interchange/export adapters;
- materials, lighting, animation, camera, environments and optimization;
- WebXR/AR/VR;
- interactive product/education/visualization experiences.

### Education/course factory
- complete curricula, modules, lessons and learning objectives;
- written content, examples, exercises, quizzes and exams;
- narration/audio/video/graphics/interactive lessons;
- learner progress, assessments, certificates and analytics;
- web/mobile/offline distributable packages;
- multilingual/localized courses;
- teacher/institution review and versioning.

### Healthcare and professional assistance
- clinic/hospital/medical administration systems;
- professional evidence retrieval, summarization and documentation assistance;
- structured workflows, appointments, records, audit and role boundaries;
- medical education/training content;
- human-review gates for high-stakes clinical recommendations;
- provenance/citation and privacy controls for regulated data;
- no autonomous high-stakes claim is considered production-ready without the required evidence and sector controls.

### Universal sector packs
AIOS must be able to compose domain packs for, at minimum:
- supermarkets/retail;
- restaurants/hospitality;
- pharmacies;
- hospitals/clinics;
- schools/universities/training centers;
- government departments/public services;
- logistics/transport;
- manufacturing/industry;
- real estate;
- professional services;
- media/advertising agencies;
- any new lawful domain expressible as roles, entities, workflows, policies and integrations.

Sector packs reuse Domain Blueprint v3 and must not become separate hard-coded product forks.

## 8. Phase 36 implementation batches

### Batch 36A — Program governance, capability registry, technology radar and reporting invariant

Scope:
- establish this master roadmap as source of truth;
- add a Phase 36 capability/maturity registry covering every taxonomy item;
- add required report/change/incident receipt format;
- CI guard for undocumented Phase 36-owned product changes;
- establish technology-radar refresh rules and supported/export format registries;
- mark previous `complete` claims as historical-scope claims, not current Phase 36 finality.

Exit gate:
- registry has no unowned capability;
- documentation/incident contract is CI-enforced;
- Owner/User product status can distinguish planned vs source-built vs rendered/connected/scaled/production-ready.

### Batch 36B — Live distributed project execution & 1000-user admission foundation

Scope:
- migrate the live `ProjectExecutionWorker` path from one sequential process to the existing Phase 23/24 distributed fabric;
- PostgreSQL-backed production-safe task/control state where required; no production SQLite single-host bottleneck;
- multiple replicas with `SKIP LOCKED`/leases/fencing, capability pools, fair scheduling, backpressure and DLQ;
- isolate user/project contexts while permitting shared physical provider endpoints;
- add job/resource class, capacity, queue-depth and wait-time metrics;
- provide Compose multi-worker profile plus multi-host/cluster deployment manifests.

Exit gate:
- no global singleton serialization;
- two or more live project workflows demonstrably execute concurrently in isolated acceptance;
- 1000 concurrent durable workflow admissions pass synthetic/fake-provider load without lost/duplicate/cross-tenant work;
- worker kill/recovery and stale completion rejection pass.

### Batch 36C — Multi-provider/model/agent execution pools

Scope:
- route project departments/tasks through the existing 15-provider catalog instead of hard-wiring the whole project cycle to one provider;
- use current connected providers according to task capability, health, quality, latency, cost, privacy and tenant policy;
- independent planner/researcher/coder/reviewer/media roles;
- provider fallback/circuit breaker only when policy allows;
- provider rate-limit aware scheduling and budgets;
- no shared mutable agent memory between tenants/projects;
- local model routing when privacy/offline policy requires it.

Exit gate:
- concurrent projects can use different provider/model plans;
- one provider outage does not globally stop all eligible projects when an approved alternative exists;
- exact provider/model/cost/evidence remains auditable per task.

### Batch 36D — Universal Creative Asset Graph & Media Orchestrator

Scope:
- unify Studio jobs, project assets and Universal Builder media targets into one durable media DAG;
- assets, revisions, provenance, prompts, rights/consent metadata, scene graph, timeline, dependencies and checksums;
- resumable render steps, partial retries, deterministic assembly and idempotency;
- S3-compatible object-storage abstraction for scale while retaining local-volume development mode;
- FFmpeg 8.1+ render/transcode workers and hardware-acceleration adapters;
- provider-neutral planning plus provider adapters for actual rendered outputs;
- output-format/profile registry and media QA.

Exit gate:
- a project can create a real rendered media asset, revise one scene without redoing unrelated work, assemble final output and retain provenance/evidence.

### Batch 36E — Image, design, branding, infographic & prompt factory

Scope:
- real image-generation/editing provider adapters;
- logos, brand systems, posters, ads, product mockups, infographics, diagrams and experimental graphics;
- prompt generation, provider-specific prompt compilation, negative prompts/constraints where supported;
- variation, upscale, inpaint/outpaint, background/subject operations where provider/runtime supports them;
- SVG/editable source plus raster exports and responsive/ad-size presets;
- brand kit and template variables.

Exit gate:
- user request -> governed prompt/design plan -> generated editable/final assets -> revision -> export, with no placeholder pretending to be rendered output.

### Batch 36F — Video, cinema, motion graphics & advertising factory

Scope:
- logo-to-video, text-to-video and image-to-video;
- multi-shot long-form scene generation with continuity metadata;
- ad/explainer/product/social/cinematic templates built from AIOS-owned schemas;
- 2D/3D motion graphics, infographic animation, kinetic typography, transitions, compositing and effect graph;
- narration/subtitles/captions/music/sound integration;
- scene-level regeneration, timeline editing and final FFmpeg assembly;
- MP4/WebM/MOV and governed additional export profiles; H.264/H.265/AV1/ProRes profiles when runtime/legal codec support is available;
- 1080p/1440p/4K output profiles, and higher-resolution workflows when input/provider/hardware supports them.

Exit gate:
- a logo + brief can produce a real multi-scene advertisement, not only a storyboard/render plan;
- long-form project can resume after worker failure and re-render only failed scenes.

### Batch 36G — Audio, voice, music, songs & podcast factory

Scope:
- STT/TTS, translation/dubbing, alignment and multi-speaker production;
- voice conversion/clone path with consent and rights evidence;
- lyrics, songwriting, composition, melody/harmony/arrangement;
- instrumental/vocal generation adapters, stems, SFX, mixing and mastering;
- podcast/narration/jingle workflows;
- waveform/loudness/format QA and multi-format export.

Exit gate:
- complete user-defined song/audio production can reach final rendered files with separated evidence for lyrics/composition/vocals/stems/mix/master.

### Batch 36H — Realtime communication, streaming & interactive media scale

Scope:
- evolve current WebRTC prototype into production service architecture;
- SFU/signaling/TURN/STUN adapters, presence, rooms, 1:1/group calls, screen share and recording boundaries;
- realtime audio/video quality metrics and adaptive bitrate;
- scalable WebSocket/realtime admission and tenant isolation;
- media recording/processing integration with Creative Studio.

Exit gate:
- concurrent realtime load tests, failover and recovery pass at the defined scale profile; no single-process signaling bottleneck.

### Batch 36I — 2D/3D/XR/game/VFX production expansion

Scope:
- 2D animation/game production templates;
- 3D asset/material/animation/environment pipeline;
- Blender/other approved renderer adapter layer when selected by the technology review;
- WebGL/Three.js/WebXR/AR/VR delivery;
- compositing/VFX integration with video;
- LOD, compression, device/performance QA.

Exit gate:
- generated assets are actually renderable/previewable and integrated into final interactive/video outputs with performance evidence.

### Batch 36J — Education & complete course factory

Scope:
- course/domain planner, curriculum and learning outcomes;
- lessons, exercises, tests, answer keys, adaptive learning paths;
- generated text/image/audio/video/interactive lesson assets;
- teacher/reviewer workflow, versioning and citations;
- learner progress, grading, certificates and analytics;
- online/mobile/offline package export and localization.

Exit gate:
- one request can produce and deliver a complete governed course package, not only an outline.

### Batch 36K — Healthcare/professional & high-stakes sector controls

Scope:
- healthcare/hospital/clinic domain packs;
- evidence-grounded professional assistance and source provenance;
- protected data boundaries, audit/retention/data-residency profiles;
- human-in-the-loop high-stakes review;
- configurable national/sector compliance adapters;
- professional education/documentation workflows.

Exit gate:
- administrative/educational/professional workflows are production-ready with tenant/privacy/security evidence; high-stakes recommendation modes remain human-reviewed unless an applicable certified deployment profile proves otherwise.

### Batch 36L — Universal business/institution/government sector packs

Scope:
- retail/supermarket inventory/POS/order workflows;
- restaurant/menu/order/kitchen/delivery/reservation workflows;
- pharmacy inventory/prescription workflow boundaries;
- school/university admissions/course/student/admin workflows;
- government case/service/form/approval/audit workflows;
- reusable sector blueprint templates plus fully custom Domain Blueprint v3 fallback;
- sector integrations and reporting.

Exit gate:
- each reference sector has a tested end-to-end example and a new unlisted sector can still be built through the general domain composer without code-forking the platform.

### Batch 36M — Unified User/Owner Creative & Project Studio

Scope:
- one discoverable user experience for software, prompts, design, image, audio, video, music, 3D/XR, courses and sector solutions;
- template/brand-kit/asset library and history;
- workflow presets comparable in usability class to major creative-generation platforms without copying their proprietary assets;
- visible queue/progress/cost/provider/status/retry/cancel/revision/download;
- Owner quotas, provider policies, moderation/safety, costs and capability enablement;
- mobile-first responsive user experience and six-locale parity.

Exit gate:
- capabilities are accessible to users, not hidden as internal APIs/source modules;
- Owner can govern them centrally without editing code or environment files for ordinary operations.

### Batch 36N — 1000+ scale, chaos, cost, security, DR and final integrated certification

Scope:
- k6 1000+ concurrent-user profiles and distributed load generation;
- 1000 concurrent workflow admission plus mixed project/studio/media workload;
- project/provider/GPU queue saturation tests and fair scheduling;
- worker/node/provider/Redis/PostgreSQL/object-store failure drills as safe isolated or controlled production exercises;
- OpenTelemetry traces/metrics/log correlation and queue/worker/GPU dashboards;
- autoscaling/resource recommendations and hardware sizing reports;
- backup/restore, RPO/RTO, artifact integrity and recovery;
- tenant isolation, security regression, abuse/rate-limit and cost-ceiling tests;
- final Owner/user/mobile/browser acceptance and updated launch report.

Exit gate:
- all Phase 36 capabilities have production evidence or an explicitly allowed external activation gate;
- 1000-user minimum passes the defined load profile;
- architecture demonstrates horizontal scale beyond 1000 without redesign;
- no known single-worker global serialization, unlogged material incident, false-rendered artifact, unresolved critical/high security issue or undocumented deployment step remains.

## 9. Required cross-batch security controls

- secret values never enter generated project/media packages;
- provider credentials remain server-side references;
- untrusted generated code/render scripts run only in isolated resource-bounded workers;
- network access is deny-by-default and capability-scoped;
- signed/checksummed artifact manifests and provenance;
- content/asset tenant isolation and authorization on every read/write/download;
- virus/file-type/decompression-bomb validation for uploads;
- bounded prompt/input/output sizes and cost ceilings;
- webhook/provider callbacks are authenticated/idempotent;
- media/voice identity/consent evidence when required by the operation;
- no raw secrets/provider IDs in public/user evidence;
- SBOM/dependency/container scanning and immutable release evidence.

## 10. Final definition of complete

The expanded AIONEX AIOS product is **not final** until every Phase 36 batch is complete and merged/deployed with retained evidence.

Completion requires:
- all required capabilities available through a user-facing or governed API workflow;
- 1000+ concurrency acceptance passed;
- distributed project execution enabled instead of singleton serialization;
- actual rendered creative media paths, not only plans/storyboards;
- complete audio/music/song and course workflows;
- sector packs and high-stakes review controls;
- latest-stable technology review completed for each batch;
- all problems/root causes/fixes documented;
- all protected CI/security/performance gates green;
- production backup/rollback/live acceptance documented;
- one final consolidated release report stating exactly what is production-ready and what, if anything, remains an external activation gate.

## 11. Phase 36 change/problem ledger

Append entries below in chronological order. Do not delete historical problems after they are fixed.

### P36-0001 — Product scope gap discovered during Owner capability review — 2026-08-17

- Batch: 36A.
- Environment: production architecture/documentation review.
- Symptom: the live project path was production-ready for governed software building but used one Project Worker; Creative Studio generated deterministic plans/source packages for audio/video/image rather than complete provider-rendered media; multiple provider capabilities existed elsewhere in AIOS but the full Project Cycle remained OpenAI-only.
- User impact: a second full-project execution waits behind the first; a user requesting Renderforest/PixVerse/Risha/Pixaflow-class final media could receive planning/source evidence rather than the requested final rendered asset.
- Root cause: platform capabilities were completed in historical phases as separate subsystems, but there was no single post-closure product contract requiring distributed live-project execution plus end-to-end Creative Media rendering across every user-facing capability family.
- Why prior tests did not prevent it: historical completion tests validated each phase against its then-current scope; they did not assert the later Owner requirement of 1000 concurrent users or require provider-rendered long-form media/song production.
- Resolution plan: Phase 36 created as the new authoritative expansion contract. Batch 36B connects the live Project path to Phase 23/24 distributed runtime; 36D–36I close real rendered media; 36N certifies 1000+ concurrency.
- Regression prevention: capability/maturity registry and mandatory report receipt are required in 36A; final completeness now depends on Phase 36 rather than historical Phase 29 closure alone.
- Production mutation in this entry: none.

## 12. Batch 36A implementation record — 2026-08-17

### 36A start / implementation scope

- Baseline: Phase 36 roadmap merged in PR #387; production remains the stable pre-36 implementation baseline.
- Gap: no machine-readable Phase 36 maturity registry, no CI-enforced reporting receipt, and Owner Completion still presented historical Phase 29 completion without the new authoritative expansion state.
- Implementation: add a Phase 36 capability registry with seven evidence-based maturity states and ownership across 36A–36N; expose the same non-secret snapshot through the public capability API and Owner finalization API; show the authoritative Phase 36 state in Owner Completion and the user Projects page; add a standard reporting receipt and GitHub CI guard.
- Technology review: 36A introduces no new production runtime dependency. It uses the repository's existing Python/FastAPI/Next.js stack and standard-library registry/checker logic. Runtime/tool versions remain governed by the technology-refresh snapshot above and must be rechecked from official upstream sources by each implementation batch.
- Security/cost: snapshot contains product metadata only, no tenant data, provider account IDs or credentials. The reporting checker inspects Git path names only. No provider call, GPU work or billable operation is added by 36A.
- Rollback: revert the 36A commit/PR; no schema migration or data transformation is involved.
- Acceptance target: registry ownership is exhaustive and unique; maturity values are ordered and truthful; 1000-user minimum is machine-readable; current batch becomes 36B after 36A closure; Phase 36-owned code changes cannot pass CI without roadmap/receipt/exemption evidence; Owner/User surfaces consume the same snapshot.

### P36-0002 — Owner finalization snapshot type regression during 36A — 2026-08-17

- Batch: 36A.
- Environment: development worktree, Owner frontend TypeScript/build gate.
- Symptom: `OwnerFinalizationSnapshot` gained the required `phase36` field, but `/owner/finalization` retained an old empty-state initializer without that field; TypeScript and the production Next.js build failed before merge.
- User impact: none; the defect was caught before PR/merge/deployment.
- Detection/reproduction: `npm run type-check` and `npm run build` reported TS2741 at `src/app/owner/finalization/page.tsx`.
- Root cause: two Owner pages instantiate the same snapshot type; the first implementation updated `/owner/completion` but missed the second initializer.
- Why prior safeguards missed it: focused source editing did not enumerate every construction site before the full TypeScript gate.
- Fix: import/use `EMPTY_OWNER_PHASE36_PROGRAM` in the second initializer.
- Security/tenant review: no API authorization, tenant data or secret handling changed.
- Regression prevention: full Owner TypeScript/build remains mandatory before 36A PR; future shared-type changes must grep all literal initializers.
- Rollout/rollback: no production rollout occurred; no rollback required.
- Residual risk: none after the complete frontend gate passes.

### 36A pre-merge validation closeout — 2026-08-17

- Machine-readable registry currently contains `54` first-class capabilities owned exactly once across batches `36A` through `36N`; the 36A governance/reporting capability is marked `production_ready` for the 36A release and the next implementation batch is `36B`.
- Core Phase 36 + historical completion contracts: `15 passed`; final full AIOS Core: `720 passed`.
- Backend Phase 36 public snapshot contract: `1 passed`; Ruff PASS; Mypy PASS across `178` backend source files; fresh PostgreSQL 16 + Redis Full Backend at Alembic `20260816_0027`: `629 passed, 1 skipped, 0 failed`.
- Owner frontend: Arabic coverage `922` strings / `5` technical tokens, TypeScript/lint/Prettier PASS, production build `86/86`, dependency audit `0 vulnerabilities`.
- VIP frontend: six-locale integrity PASS, TypeScript/lint PASS, static build `115/115`, smoke `94`, dependency audit `0 vulnerabilities`.
- Browser E2E: `10/10 passed`, including the new mobile Phase 36 status surface, Owner boundary tests, campaign readiness/account-derived-currency contracts and RTL/mobile overflow regression tests.
- Problems found during 36A are retained in the permanent ledger/receipt; no problem was silently discarded. No database migration, provider call, GPU task, paid campaign action or advertising spend was performed by 36A validation.


## 13. Batch 36B implementation record — 2026-08-17

### 36B start / implementation scope

- Baseline: Phase 36A merged as PR #388 at merge commit `c8332d225c335825fe7af6c0dd47d490b133c0e9`; all protected Phase 36A checks were green, including Production Docker. Phase 36B starts from that merged `main` baseline on `feature/phase36b-distributed-project-execution`.
- Product gap: the live PostgreSQL `ProjectExecutionWorker` had `SKIP LOCKED` and a heartbeat but each process executed only one project at a time, stale ownership relied on `updated_at`, failures were terminal, and no durable worker membership/capacity/DLQ/saturation view existed.
- Implementation in progress: explicit lease owner/expiry and fencing generation, worker membership/capacity, concurrent worker slots, resource classes, tenant-aware fair claiming, bounded retries, durable dead-letter state, queue metrics, Owner runtime visibility, Compose multi-worker profile and Kubernetes scale template.
- Production boundary: no production schema, service, container, provider budget, live user workload or public endpoint has been mutated during development. All current execution evidence is isolated/source-test evidence.
- Rollback boundary: do not apply migration `20260817_0028` to production until protected validation is complete. Source rollback remains a branch reset/revert; a schema downgrade is tested only in disposable PostgreSQL.

### P36-0003 — 1000-admission harness exceeded PostgreSQL connection capacity — 2026-08-17

- Batch: 36B.
- Environment: disposable PostgreSQL 16.14 test database during full backend regression.
- Symptom: the first 1000-admission implementation could open enough concurrent `NullPool` sessions to hit PostgreSQL `max_connections=100`; server logs recorded `sorry, too many clients already`, followed by deadlocks between still-running `project_executions` inserts and test cleanup deletes. A later project-worker regression then consumed leftover synthetic work and appeared to fail independently.
- User impact: none; production was not changed. The finding proves the original synthetic admission test did not yet model safe API backpressure strongly enough and therefore could not be used as final 1000-user evidence.
- Detection/reproduction: full backend run reported `2 failed, 633 passed, 1 skipped`; PostgreSQL server log correlated the failure with connection exhaustion and insert/delete deadlocks. Re-running the two affected tests in a fresh disposable database passed, confirming the second failure was contamination from the first test cleanup.
- Root cause: the backend intentionally uses SQLAlchemy `NullPool` for async compatibility, while the synthetic test launched many independent sessions; a test-only semaphore was too permissive in the context of the full suite and did not represent a product-level admission guard.
- Why prior safeguards missed it: focused 36B tests ran against a quieter database and passed; they did not include full-suite residual connection pressure. Historical project execution was single-worker and had no 1000-admission requirement.
- Fix plan: add an explicit bounded project-execution admission guard at the application path, strengthen the 1000-admission acceptance to exercise that bounded path, lower disposable-test database concurrency below the server connection ceiling, add an actual worker-process kill/recovery test, then rerun focused and full backend gates on a fresh database.
- Security/tenant review: the guard must not merge tenant state, expose payloads or change authorization; it only bounds concurrent admission work.
- Regression prevention: retain PostgreSQL connection-capacity evidence and require the 1000-admission test to finish with zero lost/duplicate jobs and zero database connection-exhaustion/deadlock evidence.
- Rollout/rollback: no production rollout occurred; no rollback required.
- Residual risk: **closed for the Phase 36B source/isolated acceptance boundary.** The product-level local+Redis admission guard is in place; the final fresh backend run completed `641 passed, 1 skipped, 0 failed` with zero PostgreSQL connection-exhaustion/deadlock evidence and zero leftover test-database connections. Production rollout remains separately gated.


### P36-0004 — Distributed admission waiter storm exhausted the Redis client pool — 2026-08-17

- Batch: 36B.
- Environment: disposable Redis/PostgreSQL Phase 36B acceptance environment; production untouched.
- Symptom: after adding the cross-replica Redis admission lease, the 1000-submission acceptance could exhaust the Redis client pool when the test configured more per-process admission contenders than Redis connections. The first failing contender cancelled the aggregate test, leaving database inserts unwinding while cleanup started.
- User impact: none in production; the failure was caught before PR/deployment. It exposed a real configuration invariant that must be enforced rather than relying on operator discipline.
- Detection/reproduction: Redis raised `Too many connections` from the admission Lua `EVAL`; the test then showed cancelled async tasks during teardown.
- Root cause: the distributed limiter bounded lease ownership but the configured local contender count could exceed the Redis connection pool used to acquire/retry leases. The acceptance test deliberately configured local concurrency `24` with a Redis pool of `16`, violating the safe relationship.
- Why prior safeguards missed it: the initial focused run used the local-only admission guard. The first distributed-Redis iteration added a global lease but had not yet encoded a configuration invariant between local admission capacity and the Redis pool.
- Fix: keep the two-tier order `local semaphore -> Redis global lease -> PostgreSQL`, enforce a fail-fast settings invariant that the Redis pool has headroom above local admission concurrency, make the 1000-submission test use a production-valid capacity, and always cancel/await all admission tasks before Redis/database cleanup.
- Security/tenant review: Redis stores only opaque random lease IDs and expiry scores; no tenant, project, provider or secret data is introduced. Redis failure remains fail-closed in production.
- Regression prevention: settings validation plus the 1000-task acceptance must prove no Redis pool exhaustion, no PostgreSQL connection exhaustion/deadlock, an empty admission lease set after completion, and zero leaked async tasks/connections.
- Rollout/rollback: no production rollout occurred; no rollback required.
- Residual risk: **closed for the Phase 36B source/isolated acceptance boundary.** Configuration now requires Redis pool headroom above local admission capacity; the corrected 1000-job multi-process run left the Redis admission ZSET empty, and the final backend suite passed without Redis/PostgreSQL exhaustion. Production rollout remains separately gated.


### P36-0005 — Production API database pool settings were configured but not active — 2026-08-17

- Batch: 36B.
- Environment: source/runtime architecture review plus disposable Phase 36B latency test; production unchanged.
- Symptom: after eliminating connection exhaustion and deadlocks, 1000 durable admissions completed successfully but measured `p50=14.195s`, `p95=27.143s`, `p99=28.270s`, `max=28.512s` in the single-process acceptance environment.
- User impact: no production outage; the measured latency is too high to treat the initial enqueue SLO as achieved.
- Detection/reproduction: the 1000-admission acceptance prints retained percentile evidence. Review of `app/db/base.py` showed SQLAlchemy forced `NullPool` even though `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` have long existed in configuration. Each short admission transaction therefore paid a fresh PostgreSQL connection cost.
- Root cause: a historical compatibility fix made `NullPool` global. The later production-scale configuration retained pool-size settings but never re-enabled a bounded pool for the API process.
- Why prior safeguards missed it: historical workloads prioritized cross-event-loop test compatibility and single-worker correctness; no prior phase measured 1000 near-simultaneous durable admissions.
- Fix plan: keep `NullPool` as the safe default for workers/tests, enable a bounded SQLAlchemy async queue pool only for production API containers, enforce a per-process/worker connection budget, and benchmark the exact Phase 36B admission path before adopting the change.
- Security/tenant review: pooling changes connection reuse only; session/transaction boundaries remain request scoped and tenant authorization is unchanged. Pool pre-ping remains enabled.
- Regression prevention: configuration validation must reject API pool settings that exceed the declared connection budget; full backend remains on isolated NullPool unless a test explicitly requests production-pool behavior.
- Rollout/rollback: source-only until protected validation. Rollback is disabling API pooling; no schema change is required.
- Residual risk: **pooling defect closed; latency target remains explicitly open.** API-only bounded pooling plus four-process admission reduced measured p95 from `27.143s` to a best retained `1.024s` (`p50=0.822s`, `p99=1.061s`) with zero database deadlocks/exhaustion. This is 24ms above the Phase 36 initial `<=1s` enqueue target, so the target is not claimed as passed and remains a mandatory scale/certification item rather than increasing the 60-connection API budget unsafely.


### 36B pre-merge acceptance snapshot — 2026-08-17

- Live-path architecture implemented on the feature branch: PostgreSQL `SKIP LOCKED`, explicit lease owner/expiry, monotonic fencing generation, durable worker membership, bounded retry and dead-letter state, tenant-aware scheduling, resource classes, concurrent worker capacity, queue/wait/saturation metrics, Owner visibility, local+Redis cross-replica admission backpressure, Compose multi-worker assets and Kubernetes scale template.
- API database connection behavior: production API only uses bounded async SQLAlchemy pooling; non-API workers/tests retain `NullPool`. Candidate production bounds are 4 API workers x (`12` pool + `2` overflow) = maximum `56` pooled API connections, below the declared budget `60`, leaving at least `44` of the current PostgreSQL `max_connections=100` outside the API pool ceiling. Project admission additionally caps local contenders at `14` per API worker and distributed admission ownership at `48`; Redis pool is `18` per API process and configuration rejects insufficient headroom.
- Technology refresh: SQLAlchemy `2.0.51`, Alembic `1.18.5`, Selenium `4.46.0`; current production PostgreSQL is `16.14`; Kubernetes scale template reviewed against the active 1.36 line (`1.36.2` latest published patch at review time). Official sources: `https://docs.sqlalchemy.org/en/20/`, `https://alembic.sqlalchemy.org/en/latest/changelog.html`, `https://www.selenium.dev/downloads/`, `https://www.postgresql.org/docs/16/release-16-14.html`, `https://kubernetes.io/releases/`, `https://docs.docker.com/reference/compose-file/services/`.
- Worker/process evidence: two fake-provider live project workflows overlap concurrently; stale completion after lease recovery is rejected; an actual child worker is killed with `SIGKILL`, another worker recovers the expired lease, rotates the fencing generation and completes exactly once; bounded transient failures enter retry then DLQ.
- 1000-admission evidence: four independent child API processes schedule 1000 tenant-scoped durable admissions against one PostgreSQL/Redis authority. `1000/1000` unique execution IDs and `1000/1000` distinct tenants persist queued with attempts `0`; admission lease set returns empty; no PostgreSQL `too many clients`, deadlock, PANIC/FATAL or leftover DB connections are observed. Best retained candidate latency at the conservative 56-API-connection ceiling: `p50=0.822s`, `p95=1.024s`, `p99=1.061s`. Functional 36B admission gate passes; the initial p95 `<=1s` target remains truthfully open for final scale certification.
- Fresh complete backend from zero migration through `20260817_0028`: `641 passed, 1 skipped, 0 failed` in `99.68s`.
- Complete AIOS core suite: `721 passed` in `27.44s`.
- Backend quality: dependency `pip check` PASS; Ruff PASS; Mypy PASS across `179` source files; backend verification PASS.
- Migration rollback evidence: `20260817_0028 -> 20260816_0027 -> 20260817_0028`; worker table/fencing column absent after downgrade and restored after upgrade.
- Project Worker candidate: healthcheck PASS under the real Compose mount/PYTHONPATH contract; SQLAlchemy `2.0.51`, Alembic `1.18.5`, Selenium `4.46.0`, Node `24.18.1`, npm `11.11.0`, Chromium/ChromeDriver `149.0.7827.53`.
- Owner frontend: TypeScript PASS; Arabic coverage `927` translatable strings / `5` approved technical tokens; lint PASS; production build `86/86` pages; dependency audit `0 vulnerabilities`.
- VIP frontend regression: TypeScript PASS; lint PASS; production build `115/115` pages; dependency audit `0 vulnerabilities`.
- Repository security: fail-closed secret/production audit PASS; repository hygiene audit PASS; merge-marker scan PASS; `git diff --check` PASS; Phase 36 reporting invariant PASS.
- Production mutation during this evidence run: **none**. Migration `0028`, new API pooling and distributed project workers have not yet been applied to production.
- Remaining external/rollout gates: protected GitHub PR checks; production backup/deploy/rollback/live acceptance; real multi-host worker activation still requires proven RWX/shared evidence storage (or the Phase 36D object-store backend) and actual cluster hosts/capacity.

### P36-0006 — Owner production-runtime UI coupled core readiness to optional fabric metrics — 2026-08-17

- Batch: 36B.
- Environment: protected GitHub Browser E2E for PR #389; production untouched.
- Symptom: the authenticated Owner production-runtime test could not find the retained `Public origin` contract after the new project-execution-fabric request failed to resolve the CI-only `backend` hostname. The suite result was `9 passed, 1 failed`.
- User impact: no production mutation occurred, but the UI implementation could have hidden otherwise valid production-runtime readiness data during a rolling deployment or transient failure of only the new fabric metrics endpoint.
- Detection/reproduction: PR #389 Browser E2E run `31986864145`, job `95263272121`; Next proxy logged `EAI_AGAIN backend` for `/owner/production-runtime/project-execution-fabric`, and the Owner test timed out waiting for `Public origin: https://vip-e.net`.
- Root cause: the Owner page loaded the established production-runtime snapshot and the new supplemental fabric snapshot in one `Promise.all`. Failure of either request reset both snapshots.
- Why prior safeguards missed it: local frontend type/lint/build gates verify compile-time integrity, while the pre-36B browser fixture mocked only the established production-runtime endpoint. The new secondary runtime dependency had no degraded-path browser contract yet.
- Fix: make the established production-runtime snapshot the required request and load fabric metrics as an independently degradable secondary request. Extend Browser E2E to mock and assert the fabric card, and add a separate `503` fabric regression proving core production-runtime origins remain visible.
- Security/tenant review: both endpoints remain Super Owner protected; no authorization is relaxed. The change only prevents a supplemental metrics outage from erasing already-authorized core readiness data.
- Regression prevention: Browser E2E must pass both the normal fabric rendering path and the degraded-fabric/core-runtime-preservation path.
- Rollout/rollback: no production rollout occurred; fix remains on PR #389.
- Residual risk: local regression is closed with `11/11` Browser E2E PASS, including normal fabric rendering and degraded-fabric/core-runtime preservation. The protected GitHub rerun remains required before merge.
- Local fix evidence: Owner TypeScript PASS; lint PASS; Arabic coverage `927/5`; production build `86/86`; Browser E2E `11/11 passed` in `8.4s`.

### P36-0007 — Owner degraded-fabric fix missed the dedicated Prettier gate — 2026-08-17

- Batch: 36B.
- Environment: protected GitHub Final Validation for PR #389; production untouched.
- Symptom: `Frontend Build` failed after the P36-0006 resilience fix even though TypeScript, lint, local production build and Browser E2E passed.
- User impact: none; protected CI correctly blocked merge before production.
- Detection/reproduction: PR #389 Final Validation rerun reported `Frontend Build` failure; the exact workflow-equivalent local command `npx prettier --check ...` identified only `src/app/owner/production-runtime/page.tsx` as unformatted.
- Root cause: the P36-0006 local verification reran type-check, Arabic coverage, lint, build and Browser E2E, but omitted the separate Prettier check that Final Validation enforces.
- Why prior safeguards missed it: formatting is not enforced by the Next lint/build commands, so all functional gates could pass while the dedicated formatting gate still failed.
- Fix: format the touched Owner runtime page with the repository Prettier version and rerun the exact CI formatting command plus type/lint/build/browser regression.
- Security/tenant review: formatting-only correction; no authorization, tenant, runtime or data behavior changes.
- Regression prevention: after any Owner UI edit in Phase 36, include the Final Validation Prettier command in the local pre-push gate, not only lint/type/build.
- Rollout/rollback: no production rollout occurred; fix remains on PR #389.
- Residual risk: local formatting/functional regression is closed: exact CI-equivalent Arabic/type/lint/Prettier/build gates PASS and Browser E2E `11/11` PASS after formatting. The protected Frontend Build rerun remains required before merge.
- Local fix evidence: Prettier exact CI command PASS; Owner Arabic `927/5`; TypeScript PASS; targeted lint PASS; production build `86/86`; Browser E2E `11/11 passed` in `8.2s`.
