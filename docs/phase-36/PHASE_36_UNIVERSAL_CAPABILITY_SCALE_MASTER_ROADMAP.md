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
