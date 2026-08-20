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

36D source/test evidence checkpoint (historical pre-activation):
- durable media DAG + revisions/provenance/object-store abstraction are `locally_executed`;
- dedicated FFmpeg 9.0 worker renders H.264/AAC, AV1/Opus, PNG and PCM WAV with FFprobe QA;
- VAAPI + oneVPL/QSV are compiled hardware adapters while activation remains operator/device gated;
- disposable PostgreSQL + real FFmpeg exit-gate acceptance proves partial scene re-render, final assembly, fencing/recovery and unaffected-node reuse;
- Production activation was the final boundary before `runtime_verified`/batch closure and is satisfied by the closure evidence immediately below.

36D closure status — 2026-08-17T22:44:31Z:
- protected source/hardening is merged; Production Backend and one non-root Media Worker are healthy on Alembic `0031`; real inherited S3 preflight/round-trip passed;
- real Production two-scene render/assembly plus one-scene partial revision passed with unaffected-scene checksum reuse, Studio revision materialization, provenance and fenced durable execution;
- canary DB rows and S3 objects were removed, active Project/Media work returned to zero, `/ready` is `20/20` HTTP 200, and public/private ingress boundaries remain healthy;
- `creative-asset-graph`, `media-render-transcode`, and `object-storage-media` are `runtime_verified`; **36D=complete, 36E=in_progress, current_batch=36E**. Full evidence is retained in `docs/phase-36/receipts/36D-2026-08-17-media-orchestrator.md`.


Post-closeout runtime refresh — 2026-08-17T23:08Z:
- merged source and live API remain aligned at `main@12e7d01`; Backend reports `current_batch=36E`; one non-root Media Worker is healthy on the latest rebuilt image; Alembic remains `0031`; all synthetic Media/Studio canary rows and objects remain cleaned. Runtime refresh details are retained in the 36D receipt.

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

Current 36E foundation checkpoint — 2026-08-18:
- live provider inventories and current official documentation select OpenAI `gpt-image-2`, Gemini `gemini-3.1-flash-image` / `gemini-3.1-flash-lite-image` / `gemini-3-pro-image`, and Fireworks FLUX Image API as the initial launch pool; deprecated Imagen is not targeted;
- provider-neutral `DesignPlan` / `BrandKit` / responsive preset / prompt compiler foundation is locally verified, and Production Studio Image output now emits a governed design plan plus an editable SVG explicitly marked as a template;
- no template/prompt artifact is promoted as a rendered/final image; real provider execution, edits, derivatives and Production evidence remain required before any 36E maturity/closure transition;
- full checkpoint evidence is retained in `docs/phase-36/receipts/36E-2026-08-18-design-image-foundation.md`.
- Checkpoint 2A adds a durable `DesignImageExecution` authority at Alembic `20260818_0032`: explicit arm-before-spend, provider/model/operation allowlisting, DAG dependency gating, lease/fencing/retry, raster-envelope validation, S3/checksum/evidence and Studio revision materialization are locally proven without any provider request.
- Fresh PostgreSQL 16 + 2A authority tests are `5/5 PASS`; migration `0032 -> 0031 -> 0032` PASS. The next boundary is provider HTTP adapters/worker under the same explicit arm gate; 36E remains `in_progress`.
- Checkpoint 2B adds hardened OpenAI/Gemini/Fireworks image HTTP adapters plus a separate non-root `image-execution` worker profile that is live-disabled by default. Fake-HTTP/provider plus real durable-worker DB integration is `22/22 PASS`; no live image provider request/spend is claimed yet.
- Checkpoint 3A hardens provider billing evidence before the first paid image call: Alembic `20260818_0033` makes unknown actual cost nullable and records a governed cost basis; Fireworks fixed/step pricing and Gemini/OpenAI usage-based pricing paths are locally verified. Focused accounting/runtime suite is `23/23 PASS`, migration `0033 -> 0032 -> 0033` PASS; Production remains live-disabled pending protected merge/deploy.
- Checkpoint 3B live acceptance proves OpenAI GPT Image 2 end-to-end on Production (`$0.0067` actual provider usage) with S3/DAG/Studio revision and complete synthetic cleanup. Fireworks Schnell is live-gated because the current credential cannot access/deploy the configured model; Gemini Flash Lite Image is live-gated because the current API key reports image free-tier quota limit `0`. Persistent image worker remains live-disabled. Token-count usage evidence is retained while credential tokens remain redacted; Phase36E stays `in_progress`.
- Checkpoint 3B1 hardens provider-native output contracts before spend: Gemini 3.1 Flash Lite is explicitly 1K/JPEG-only in the launch capability matrix, and unsupported provider/model output formats are rejected before execution creation/arming. Fireworks and Gemini remain external live gates; the persistent image worker stays live-disabled.
- Checkpoint 3C closes Stage 3: OpenAI GPT Image 2 reference-image edit is Production-proven through S3 parent-node input, durable provider execution, output validation, Media DAG and Studio revision. Actual cost `$0.014912`; input/output usage tokens retained safely; synthetic DB/S3 cleanup complete. PR #434 provider-format hardening is now merged and deployed with the persistent image worker still live-disabled. Stage 4 remains before Batch 36E closure.
- Checkpoint 4A starts Stage 4 with fail-closed provider-aware live routing: static capability never implies live readiness; exact operation/output-format evidence is required, current external gates cannot silently become fallbacks, and responsive raster derivative plans are deterministic/governed with transparent JPEG excluded. Focused Design Factory suite is `14/14 PASS`; no provider spend or persistent worker arm is introduced.
- Checkpoint 4B1 establishes the governed local derivative engine: exact Sharp `0.35.3` on Node 24, source/output checksums and raster dimensions are independently verified, actual transparency fails closed for JPEG, and a real synthetic PNG -> WebP image-level transform passes. The initial co-located media-worker packaging is superseded by 4B2 before merge; no provider spend, schema change or Production worker restart is introduced.
- Checkpoint 4B2 wires Stage 4A live-evidence routing into no-spend durable `DesignImageExecution` creation and governed responsive `MediaRenderStep(engine=sharp)` children. FFmpeg claims are now explicitly `engine=ffmpeg`; a separate live-disabled derivative worker owns only Sharp steps, sanitizes its Node subprocess environment, fences/rechecks outputs, and materializes Studio only after the whole derivative DAG completes. Real standalone Node `24.18.1` + Sharp `0.35.3` + libvips `8.18.3` PNG/WebP/JPEG smoke passes; focused Sharp `5/5`, routed image runtime `9/9`, affected Phase36D `10/10`, Design Factory `14/14`.
- Checkpoint 4B3 closes the Stage 4B Production activation gate: protected PR #438 merged as `7afe037289f2187eb64f515d3eccd6d84c33267c`; fresh PostgreSQL backup/restore and rollback image anchors PASS; Backend/FFmpeg/Image/Derivative services are healthy with both persistent image-execution flags still false. A Production no-provider-spend canary proved FFmpeg-vs-Sharp claim isolation, processed `3/3` PNG/WebP/JPEG derivatives through real S3 + Sharp, materialized one Studio revision, recorded zero provider spend/request ID, and cleaned synthetic DB rows/S3 objects to zero. Evidence SHA-256 `e0fab1f418b547f08f74c5316432440c420e1afb28240aeb88cdac3b1c2ef0a0`. Stage 4 next moves to separately bounded inpaint/background-remove acceptance and required design-family/editable-source exit evidence; 36E remains `in_progress`.
- Checkpoint 4C1 proves OpenAI GPT Image 2 `inpaint` and `variation` live on Production while correcting false transparency/background-removal claims. Two independent inpaint canaries PASS (retained evidence `f981e250...fa630` and `0434b05e...548f59`); variation PASS costs `$0.014197` with verified S3/DAG/Studio evidence `fef205fd...123ce`. Background-remove fails without spend; an allowlisted diagnostic identifies HTTP `400`, `code=invalid_value`, `param=background` (`c6f0e693...072b92`), and a separate generation A/B with `background=transparent` also fails before spend (`5e002444...82f5e9`). Source hardening removes GPT Image 2 background-remove/transparency claims, rejects known-invalid contracts before durable row creation and before HTTP, and trusted runtime evidence advances only `generate/edit/inpaint/variation`. No migration; Stage 4 next moves to the remaining design-family/editable-source exit evidence; 36E remains `in_progress`.
- Checkpoint 4C2 closes the protected operation-truth deployment gate: PR #440 merged as `db77eb733bf69e9ed98cb4a95a2e2d8f37363bb8`; fresh backup/restore PASS (`99868dd8...cb6abb`), rollback image retained, and only Backend + Design Image Worker were recreated on `sha256:7f08c2e8...22bf5c`. Persistent image/derivative flags remain false; deployed pre-row guard keeps execution rows `0 -> 0` and adapter MockTransport records `http_calls=0` for known-invalid transparency/background-remove. All four services Healthy, queues zero, `/ready` 20/20, public/portal 200 and Owner Access 302. Stage 4C is merged/deployed; Stage 4D editable-source protected validation is next.
- Checkpoint 4D1 is a source/test candidate initially built on #440 head `f9133a0`, fast-forwarded/reverified on merged `main@db77eb7`, and then synchronized onto latest `main@db1218e` after #441 merged: a deterministic `36E.editable.v1` SVG embeds the verified real raster as the visible base while keeping brand/copy guides separately editable; safe pipeline metadata excludes prompts/briefs/storage keys; editable object I/O occurs outside final DB locks with lease renewal and forced-finalization cleanup; Studio exposes a tenant-scoped checksum-verified editable download. Post-merge focused Stage4D/Studio regression `6/6 PASS`, parent Factory `15/15`, Ruff/Mypy/compile/diff PASS. No migration/provider spend/Stage4D Production mutation; latest-main sync is complete, next is protected CI + no-spend Production editable-source canary.
- Checkpoint 4D2 closes the Production rendered-editable gate: protected PR #442 merged as `1cbb9b5741f5d87e016176e657f4cd12d7dba3bf`; fresh backup/restore and rollback anchors PASS; Backend + Image Worker run `sha256:45577b26...fe7119`, Derivative Worker runs `sha256:abba615a...27dee0`, FFmpeg remains untouched. A no-provider-spend Production canary processed `3/3` PNG/WebP/JPEG derivatives, materialized one checksum-verified `36E.editable.v1` SVG bound to the real primary raster, proved Studio/public storage-locator redaction and governed presigned download, then deleted `5/5` synthetic objects and all synthetic DB rows. Provider request/spend remained absent/`$0.00`; evidence SHA-256 `9a53ba504a7fc7833e2f4ce0a8881b60ba179f9e8ae1e5095f10e328c0f18eb7`. All services Healthy, flags false, queues zero. Stage 4E design-family exit evidence is next; 36E remains `in_progress`.

- Checkpoint 4E1 closes the design-family exit evidence: bounded sequential GPT Image 2 low-quality canaries prove all eight required families (`logo`, `brand-system`, `poster`, `advertisement`, `product-mockup`, `infographic`, `diagram`, `experimental-graphic`) through real provider raster -> Sharp responsive derivatives -> checksum-bound `36E.editable.v1` -> Studio revision/export. Combined result: `8` provider calls, `32` derivatives, `8` revisions, `$0.046500` actual cost, `48/48` synthetic objects deleted/verified missing and all synthetic DB rows zero; final evidence SHA-256 `565ad75118f7531389cb8dc5914833641f42fabefe4036ebe0cc6823cb11ce97`. All Phase 36E closure checklist items are PASS; the protected closeout candidate sets `36E=complete`, `36F=in_progress`, `current_batch=36F` after merge/deploy. No 36F implementation is included in the closeout.
- Checkpoint 4E2 completes Phase 36E Production activation: protected PR #444 merged as `416f5fe7feac5e7f9fb7f9162668ad9aa3abbf00`; Production source fast-forwarded from `4538051`, Backend was restarted to reload the mounted registry, and only Owner Frontend was rebuilt/recreated on `sha256:9f262d5f...240572` with rollback image retained. Runtime/API now report `36E=complete`, `36F=in_progress`, `current_batch=36F`; Alembic stays `0033`; all checked services Healthy; flags false; queues zero; `/ready` 20/20; public/portal 200 and Owner Access 302. Activation evidence SHA-256 `e852e48222a337b579cd2a3e11cae1021b01ae6211c777121bd9f280ba1de31d`. **36E is closed; 36F is current.**


### P36-0017 — GPT Image 2 generic background schema did not match live model/account contract — 2026-08-18

- Batch: 36E Stage 4C.
- Environment: bounded Production image-provider acceptance; persistent workers remained disabled.
- Symptom: the internal `background-remove` operation mapped a GPT Image 2 edit to `background=transparent`; the provider rejected it as HTTP `400 provider_request`. A generation A/B that changed only `background=transparent` was also rejected before image output.
- User impact: none. The operation had not been promoted to runtime-ready and every failed canary was synthetic, one-shot and cleaned. No repeated user spend occurred.
- Detection/evidence: first failures produced no request ID/output/cost. One diagnostic retry retained only safe fields and proved `type=image_generation_user_error`, `code=invalid_value`, `param=background`; provider message content was not stored, only its hash/length. Diagnostic evidence SHA-256 `c6f0e693e95134e6f9cbdf2d1500d04108a14eab7f0ce3b10b562f7bbf072b92`. Transparent-generation evidence SHA-256 `5e00244440eae715537d887fd6d9a7308cb8f36d7e0018fa4850dad9ae82f5e9`.
- Root cause: the Phase36E launch matrix treated a generic Images background contract as model-specific GPT Image 2 capability without separate live acceptance. Static/generic provider schema was therefore broader than the live credential/model endpoint behavior.
- Why prior safeguards missed it: Stage 3 had proven normal generation and reference editing only; Stage 4A intentionally required separate runtime evidence for unproven operations, so the false static capability had not yet reached live routing, but planning metadata still overstated transparency/background-remove.
- Fix: remove `background-remove` from GPT Image 2 operations; set GPT Image 2 transparency support false for the current launch matrix; require complete capability matching during prompt compilation; reject transparent GPT Image 2 durable specs before row creation; and retain a defense-in-depth adapter guard that makes zero HTTP calls for the known-invalid contracts.
- Positive operation evidence: inpaint and variation are separately live-proven and remain available. Variation evidence SHA-256 `fef205fd2f240f25dd2ec5b871a485465f92ded9be4137e0101302a7ee8123ce`.
- Security/tenant review: all probes used synthetic tenant-scoped S3/DAG inputs; raw provider errors, prompts and credentials were not retained; all synthetic DB rows and objects were cleaned; persistent image execution remained disabled.
- Regression prevention: Factory routing, provider-adapter and durable-execution tests must prove background-remove/transparency fail pre-spend while inpaint/variation route only with explicit trusted runtime evidence. Any future re-enable requires new model-specific live evidence rather than documentation inference.
- Production boundary: correction is source-only until protected merge/deploy; current accepted Stage 4B Production remains healthy and fail-closed.

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

Current 36F Stage 1 checkpoint — 2026-08-19:
- Phase 36E activation evidence is merged (`main@5ed6157`) and Production truthfully reports `current_batch=36F`; existing Phase 36D Media DAG/S3/FFmpeg 9 infrastructure is reused rather than duplicated.
- Added governed `36F.video-plan.v1` planning/continuity contracts and conservative provider compilation for current credential-visible Sora 2/Pro plus Gemini Omni/Veo models. Static/model-inventory visibility never implies live video readiness; Fireworks is not claimed as a video generator in this checkpoint.
- Production Studio Video now emits a deterministic four-scene VideoPlan, `36F.continuity.v1`, governed shot list/subtitles/provider prompts and an explicitly planned FFmpeg handoff while retaining `provider=None`, `external_requests=0`, `external_cost_usd=0`. VideoFactory `7/7` and Studio/36D regression `16/16` PASS; Ruff/Mypy/compile/diff PASS. No migration/provider video request/spend/Production mutation. Full evidence: `docs/phase-36/receipts/36F-2026-08-19-video-factory.md`.
- Next: dedicated durable async VideoExecution authority + exact provider adapters; only then bounded live scene generation and the real multi-scene advertisement/resume exit gate.


- Checkpoint 36F-1B: protected PR #446 merged as `6792872f5abb41432e39d7435b8baa15607862cf`; Backend-only Production activation proved `36F.video-plan.v1` remains planned/provider-neutral with zero external video requests/spend, while existing Media/Image/Derivative workers stayed healthy/unchanged. Deployment evidence SHA-256 `8d273b2346be71a964bea2e26b7f1382334a91de43a7ec8d60b019c54658713d`.
- Checkpoint 36F-2A candidate adds Alembic `0034` + dedicated durable async `VideoExecution` authority: explicit arm, idempotency, durable `submitting -> reconcile` crash ambiguity state, separate submit/observation budgets, immutable provider job ID, lease/fencing/recovery, sanitized usage/cost/output evidence and MP4 scene-node completion through the existing Media DAG. Disposable PostgreSQL `0034 -> 0033 -> 0034` PASS; final combined affected regression `20/20 PASS`; no provider video HTTP/spend/Production migration. Next is protected merge/deploy of 0034, then exact provider adapters + live-disabled worker/pipeline with provider-specific reconciliation.
- **Stage 2A merged/deployed:** PR #447 merged as `4487b9e86e787c6621900cdecc9f4dfee9860b07`; backup/restore PASS preceded Production Alembic `0034`; Video rows/worker/provider spend stayed zero. Evidence SHA-256 `fba1aa52bb3328f19ff82bf5c056aa1a09a0836321b09f902b0f6f8d2442f3a8`.
- **Stage 2B merged/deployed disabled:** PR #449 merged as `77d282ae03b8906e23d420318a43753d53f8210f`; the exact Sora text-to-video pipeline/transport and FFmpeg-9 Video Provider Worker are now deployed on Production Alembic `0034` with `VIDEO_EXECUTION_LIVE_ENABLED=false`. Worker health is green with cycles/errors `0/0`, VideoExecution rows remain zero and observed provider Video spend remains `$0.00`. Evidence SHA-256 `307d3daad9e8bff97ff7d001268754ce6ffe3fe93fb8df2d61badc5e1c7b0a3c`. The next gate is a separately owner-approved one-shot cost-capped Sora canary; inventory alone cannot route.
- **Stage 3A Sora text-to-video live acceptance PASS:** one owner-approved `sora-2` 4-second 1280x720 opening scene was armed with `max_attempts=1`; exactly one provider submission completed after 10 polls, passed FFmpeg/ffprobe QA, recorded official fixed-second cost `$0.40`, then its single object and complete synthetic DB graph were deleted/verified. Persistent Video Worker stayed hard-disabled and post-cleanup VideoExecution remained `0/0`. Evidence SHA-256 `d73501faf33853a6345df4f16ec5972960b8a65c0696d6778b0ad790546aa0f4`. This proves text-to-video only; image/logo/reference and Gemini/Veo remain separate gates before multi-scene/resume exit evidence.
- **Stage 3B reference transport merged/deployed disabled + image/logo live acceptance PASS:** protected PR #452 merged as `2d632c75edaf427129e7974bb867c789520ac23b`; no migration was required and only the Video Provider Worker was rebuilt/recreated on `sha256:9a561b195bcfb9d048633f424a08e14d75baa405a7a81ab92288f8cacb2f479d`, still hard-disabled. Image-to-video then passed one cost-capped `sora-2` 4s/1280x720 submit at `$0.40`, completed after 11 polls and cleaned all synthetic objects/rows; evidence SHA-256 `bd3234b3e06a62082d474c46d209c6c267b894710a7d2c2b434357f480eb2f52`. Its docs PR #453 merged as `f50abafcb1f2df6a6e62de8d49548232f8ceb1da`. A separate logo-specific no-spend precheck then passed, followed by one `logo-to-video` submit (`max_attempts=1`) completing after 14 polls; FFmpeg/ffprobe accepted a 1,840,600-byte MP4, actual cost `$0.40`, both input/output objects and all synthetic rows were deleted/verified, persistent worker stayed disabled with cycles/errors `0/0`, global VideoExecution rows `0`, `/ready` `10/10`. Sanitized logo evidence SHA-256 `c500909a52f14ce0089f77dc58b70a54ddd36c521bdb9a56905baa8b2bb71719`. Next: separate cost-capped `reference-to-video`; shared transport does not promote it automatically.


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
- Residual risk: **closed for the Phase 36B source/isolated boundary.** API-only bounded pooling plus four-process admission reduced measured p95 from `27.143s` to `0.990s` (`p50=0.804s`, `p99=1.005s`, `max=1.009s`) with zero database deadlocks/exhaustion. The `<=1s` Phase 36B enqueue target passes without increasing the declared 60-connection API budget. Broader mixed-workload scale remains owned by 36N.


### 36B pre-merge acceptance snapshot — 2026-08-17

- Live-path architecture implemented on the feature branch: PostgreSQL `SKIP LOCKED`, explicit lease owner/expiry, monotonic fencing generation, durable worker membership, bounded retry and dead-letter state, tenant-aware scheduling, resource classes, concurrent worker capacity, queue/wait/saturation metrics, Owner visibility, local+Redis cross-replica admission backpressure, Compose multi-worker assets and Kubernetes scale template.
- API database connection behavior: production API only uses bounded async SQLAlchemy pooling; non-API workers/tests retain `NullPool`. Candidate production bounds are 4 API workers x (`12` pool + `2` overflow) = maximum `56` pooled API connections, below the declared budget `60`, leaving at least `44` of the current PostgreSQL `max_connections=100` outside the API pool ceiling. Project admission additionally caps local contenders at `14` per API worker and distributed admission ownership at `48`; Redis pool is `18` per API process and configuration rejects insufficient headroom.
- Technology refresh: SQLAlchemy `2.0.51`, Alembic `1.18.5`, Selenium `4.46.0`; current production PostgreSQL is `16.14`; Kubernetes scale template reviewed against the active 1.36 line (`1.36.2` latest published patch at review time). Official sources: `https://docs.sqlalchemy.org/en/20/`, `https://alembic.sqlalchemy.org/en/latest/changelog.html`, `https://www.selenium.dev/downloads/`, `https://www.postgresql.org/docs/16/release-16-14.html`, `https://kubernetes.io/releases/`, `https://docs.docker.com/reference/compose-file/services/`.
- Worker/process evidence: two fake-provider live project workflows overlap concurrently; stale completion after lease recovery is rejected; an actual child worker is killed with `SIGKILL`, another worker recovers the expired lease, rotates the fencing generation and completes exactly once; bounded transient failures enter retry then DLQ.
- 1000-admission evidence: four independent child API processes schedule 1000 tenant-scoped durable admissions against one PostgreSQL/Redis authority using the exact pre-merge production shape (`12+2` per-process DB pool, budget `60`, Redis pool `18`, local admission `14`, global limit `48`). `1000/1000` unique execution IDs and `1000/1000` distinct tenants persist queued with attempts `0`; admission lease set returns empty; no PostgreSQL `too many clients`, deadlock, PANIC/FATAL or leftover DB connections are observed. Final retained latency: `p50=0.804s`, `p95=0.990s`, `p99=1.005s`, `max=1.009s`; the functional gate and Phase 36B p95 `<=1s` target both pass.
- Fresh complete backend from zero migration through `20260817_0028`: `641 passed, 1 skipped, 0 failed` in `100.26s`.
- Complete AIOS core suite: `721 passed` in `27.07s`.
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
- Residual risk: **closed.** Local Browser E2E is `11/11` PASS including the degraded-fabric/core-runtime preservation path, and the protected PR #389 `Owner and VIP browser boundaries` rerun is PASS.
- Fix evidence: Owner TypeScript PASS; lint PASS; Arabic coverage `927/5`; production build `86/86`; local Browser E2E `11/11` PASS; protected `Owner and VIP browser boundaries` PASS.

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
- Residual risk: **closed.** Exact CI-equivalent Arabic/type/lint/Prettier/build gates PASS, Browser E2E `11/11` PASS after formatting, and the protected PR #389 `Frontend Build` rerun is PASS.
- Fix evidence: Prettier exact CI command PASS; Owner Arabic `927/5`; TypeScript PASS; targeted lint PASS; production build `86/86`; Browser E2E `11/11` PASS; protected `Frontend Build` PASS.

### 36B post-merge production activation checkpoint — 2026-08-17

- Merge evidence: PR #389 merged into `main` as `061f63dd47093cc3049a0feda8bb6667aeac9f46` after every required protected check passed, including Backend Tests, Production Docker, Browser boundaries, Frontend Build, CodeQL, secret/hygiene, SBOM, dependency security and Phase 36 reporting.
- Safe production boundary at checkpoint creation: source is merged, but production migration `20260817_0028`, API pooling changes and distributed project-worker replica activation have **not yet** been applied.
- Final isolated evidence before production: Full Backend `641 passed, 1 skipped, 0 failed` in `100.26s`; AIOS Core `721/721` in `27.07s`; exact four-process 1000 admission `1000/1000` with `p95=0.990s`; Owner Browser `11/11`; migration downgrade/upgrade and real SIGKILL recovery pass.
- Maturity truthfulness after production activation: `distributed-project-execution=runtime_verified`, `horizontal-worker-scaling=runtime_verified`, `thousand-user-admission=locally_executed`; Batch 36B remains `in_progress` until this source/report closeout is merged. Real multi-host/RWX scaling is not claimed.
- Rollback anchor: pre-36B main is `c8332d225c335825fe7af6c0dd47d490b133c0e9`; production activation must create a fresh data backup before mutation and must not claim real multi-host scaling without RWX/object-store evidence plus actual hosts.
- Production backup gate: fresh archive `/opt/AIOS/.deployment-backups/phase36b-production-activation/aios-20260817T023406Z.tar.gz` created before schema/service mutation; SHA-256 PASS. Restore smoke into disposable PostgreSQL PASS with Alembic `20260816_0027`, one retained project execution and 12 backup records. No active project execution existed at the production baseline.
- Production migration gate: merged candidate applied `20260816_0027 -> 20260817_0028` successfully. Post-migration evidence: `project_execution_workers` present, `fencing_token` present, retained project executions `1 completed`, active executions `0`, Backend ready PASS and pre-rebuild Project Worker health PASS.
- Controlled rebuild gate: pre-36B Backend/Project Worker image IDs retained under rollback tags `aionex-aios-backend:pre-phase36b-20260817T023406Z` and `aionex-aios-project-worker:pre-phase36b-20260817T023406Z`. New Backend recreated alone and reached healthy/ready; new Project Worker recreated alone with Phase36B override and reached healthy. Worker registry now reports `1 online`, total capacity `2`, active `0`; no active execution was interrupted.
- Same-host scale/live gate: Project Worker scaled to two healthy replicas on the same host; durable registry reports `2 online`, aggregate capacity `4`, active `0`; live fabric queues/retries/DLQ/running all `0`. API `/ready` passed `20/20` with `p95=0.1457s`; public/user/owner ingress returned HTTP 200. Idle Worker2 stop/rejoin degraded capacity from 4 to 2 while Worker1 remained healthy and restored capacity to 4 after rejoin; active project jobs remained `0`.
- Next safe transition: same-host scale/live acceptance + P36-0008 source fix are complete -> final Phase36/production-hardening/security/diff gates -> protected production-activation PR -> merge only when green -> final merge-SHA/status closure before 36C.

### P36-0008 — PostgreSQL healthcheck generated root-role authentication noise — 2026-08-17

- Batch: 36B production activation review; defect predates the 36B deployment.
- Environment: production PostgreSQL container logs and production Compose source.
- Symptom: PostgreSQL logged `FATAL: role "root" does not exist` every 10 seconds while Docker still reported the database healthy.
- Detection: activation log review found the pattern after deployment; a pre-activation 10-minute window already contained 59 identical entries, proving it was not introduced by Phase 36B.
- Root cause: PostgreSQL healthcheck used `pg_isready --host 127.0.0.1 --port 5432 --quiet` without `--username`/`--dbname`; `pg_isready` therefore attempted the container execution user (`root`).
- Impact/severity: low operational/logging noise only; database health, application queries, backup/restore, migration and connection capacity were unaffected. No user-facing outage.
- Resolution: source fixed across dashboard production Compose, deployment production Compose, development Compose and PostgreSQL recovery/reconcile readiness probes. All probes now pass the configured user/database and no credential value is committed. The already-healthy production PostgreSQL container is intentionally not recreated solely to remove low-severity historic log noise; the corrected healthcheck becomes active on the next controlled PostgreSQL recreate/maintenance.
- Fix evidence: all three Compose configs parse successfully; `recover-postgres-login.sh` and `reconcile-postgres-credentials.sh` pass `bash -n`; backend database settings/credential regressions `53/53 PASS`; source regression rejects the bare root-default `pg_isready` form.
- Security review: no credential value is added to source; Compose expands existing required environment variables inside the container.
- Regression prevention: production Compose tests must assert explicit user/database healthcheck arguments and reject the root-default form.
- Production rollback/activation boundary: no PostgreSQL runtime change is required for this source correction during the current 36B activation; production data/schema/services remain at the already-verified Phase 36B state.

### 36B final closure — 2026-08-17

- Protected closeout: PR #391 merged into `main` as `30881343e78ccfa4887df32417a4bda85a19af55`; all required checks passed, including Backend Tests, Production Docker Build, Browser boundaries, Frontend Build, CodeQL, repository secret/hygiene, SBOM, dependency security and Phase 36 reporting.
- Production acceptance retained: Alembic `20260817_0028`; Backend healthy with bounded async pool `12+2` under budget `60`; Redis admission `18/14/48`; two same-host healthy Project Worker replicas with aggregate capacity `4`; live queue/retry/DLQ/running all `0`; Worker stop/rejoin drill passed; API `/ready` `20/20` HTTP 200 with `p95=0.1457s`.
- Data/rollback evidence retained: fresh pre-activation backup SHA-256 PASS and disposable restore smoke PASS; one pre-existing project execution remained `completed`; no active project execution was interrupted during migration/rebuild/scale.
- Maturity boundary remains truthful: `distributed-project-execution=runtime_verified`, `horizontal-worker-scaling=runtime_verified`, `thousand-user-admission=locally_executed`. No `scaled` or `production_ready` maturity is claimed without the corresponding multi-host/final-certification evidence.
- External gate retained: real multi-host Project Worker activation still requires RWX/shared evidence storage or an object-store evidence backend plus actual hosts/capacity; broad mixed-workload 1000+ chaos/DR certification remains owned by 36N.
- Program transition: Batch `36B` is now `complete`; Batch `36C` becomes `in_progress` and the authoritative `current_batch` is `36C`. This closure update starts no Phase 36C runtime development.
- Safe handoff: begin 36C only from merged `main` after its own baseline/inventory/technology/security review; do not repeat the completed 36B backup, migration, rebuild, scale or load gates unless a future regression or rollback requires them.

### P36-0009 — Backend Phase 36 public contract retained the previous current batch — 2026-08-17

- Batch: 36B final status closure; production runtime untouched.
- Environment: protected Backend Tests on final status-only PR #393.
- Symptom: Backend Tests failed after the registry truthfully moved `36B` to `complete` and `36C` to `in_progress`; `web-dashboard/backend/tests/test_phase36_program_capabilities.py` still asserted `current_batch == "36B"`.
- User impact: none; the endpoint implementation already consumes the authoritative shared Phase36 snapshot, and protected CI blocked the bookkeeping merge before an inconsistent contract test could enter `main`.
- Root cause: the root Phase36 governance test and Backend public endpoint contract are separate regression layers; the closure update advanced the root governance expectations but missed the duplicate Backend endpoint expectation.
- Why prior safeguards missed it: local closure validation ran all root `tests/test_phase36*.py` (`15/15 PASS`) but did not include the Backend-specific public capability contract.
- Fix: update the Backend endpoint contract to assert `current_batch=36C`, `36B=complete`, and `36C=in_progress` while retaining the existing non-secret snapshot assertions.
- Regression prevention: every future Phase36 batch transition must update and run both root governance tests and the Backend public capability snapshot contract before push.
- Production/security boundary: test/report-only correction; no runtime implementation, production service, schema, secret, provider call or user workload is changed.
- Fix evidence: focused Backend public capability contract `1/1 PASS` in the retained Phase36B backend test image; root Phase36/reporting gates passed, and PR #393 subsequently passed every required protected check and merged as `fc589766adb677d2a9510344997fc948cae1a030`.

## 14. Batch 36C baseline / implementation record — 2026-08-17

### 36C baseline inventory

- Start point: Phase 36B is fully closed; PR #393 merged as `fc589766adb677d2a9510344997fc948cae1a030`; production remains healthy on the accepted Phase 36B runtime with two same-host Project Workers and zero active ProjectExecution jobs at the 36C inventory checkpoint.
- Provider production state, non-secret: 15 AI provider rows exist; 13 are `connected`, while Azure OpenAI and AWS Bedrock are `configured`. No durable `ai_agents` rows currently exist. The final Backend catalog additionally contains Tripo3D/Meshy as catalog-only 3D connector types; they are outside the 36C AI execution pool.
- Reusable foundation: `MultiModelPlatform`, `ModelRouter`, `AIRoutingLayer`, provider health, failover, queueing, rate limiter, retry manager, cost governor, prompt firewall, audit journal, provider/model catalog, durable `AIProvider`/`AIAgent` models and organization-scoped `ScopedMemory` already exist and have historical tests. 36C must integrate these capabilities rather than create a second provider framework.
- Live Project Cycle gap: `project_execution.py` remains OpenAI-specific (28 OpenAI literals, eight allowed-OpenAI endpoint references and fixed `gpt-5-mini` planning model); therefore concurrent distributed Project Workers cannot yet select independent provider/model plans by role/task.
- Memory boundary: production `ScopedMemory` keys by `organization_id + scope_type + scope_id` and validates project/workspace/user/worker ownership. Legacy `src/aios/memory.py` is project-only and is not acceptable as the production agent-memory authority for 36C.
- Technology review: current primary REST protocols remain supported by official provider documentation. Gemini `generateContent` remains available, while Google's current API reference recommends Interactions for new agentic workflows; migration, if any, must be evidence-driven and backward-compatible. No dependency/protocol change is made in this baseline.
- Maturity remains truthful: `multi-provider-project-routing=source_built` and `tenant-agent-memory-isolation=source_built`; 36C remains `in_progress`. No maturity is raised by inventory alone.
- Safe implementation sequence: tenant-safe route-plan contract -> durable audit/evidence schema if required -> fake-provider adapter and role plans -> distributed rate/budget/health coordination -> failure/fallback/isolation tests -> provider-specific model capability validation -> protected PR -> controlled live provider acceptance -> production rollout/closure.

### P36-0010 — Existing provider integration is not a production multi-tenant/distributed boundary

- Batch: 36C.
- Environment: source architecture/security inventory; production untouched.
- Symptom: `AIWorkItem` carries project/actor but no organization identifier, while routing health/metrics/cost and provider rate-limit state are process-local. Directly wiring this object into the two distributed Project Workers could make tenant authorization implicit and quota/failure state inconsistent across workers.
- User impact: none; 36C runtime integration has not started.
- Root cause: the provider routing integration was built as a reusable subsystem before the durable multi-tenant ProjectExecution production path existed.
- Why prior safeguards missed it: Phase 7/29 provider tests validated routing/provider behavior and Phase 29F validated tenant-scoped memory independently; no prior acceptance gate required their direct use from distributed ProjectExecution.
- Required fix: make organization/project/execution/task scope explicit and immutable; resolve provider records inside that tenant boundary; persist route/audit evidence; coordinate rate/budget/health state through a shared authority; fail closed when tenant/provider/locality policy cannot be proven.
- Regression prevention: cross-tenant route/memory/provider-ID tests; two-worker shared quota/circuit state tests; raw credential/provider-secret scans; fallback-denied tests for restricted/local policy.
- Production boundary: no provider calls, secrets, DB writes, schema changes or service restarts in this finding.

### P36-0011 — Production ProjectExecution remains hard-wired to OpenAI

- Batch: 36C.
- Environment: source inventory; production untouched.
- Symptom: ProjectExecution loads one provider secret contract, validates OpenAI models/endpoints, uses a fixed `gpt-5-mini` planning model and defaults evidence provider fields to OpenAI instead of selecting from the durable provider catalog.
- User impact: current projects cannot obtain independent planner/researcher/coder/reviewer provider plans even though the provider subsystem supports routing and production has 13 connected AI providers.
- Root cause: the governed Project Cycle reached production in Phase 22 with a deliberately narrow OpenAI execution path; later provider completion did not rewrite the live Project Cycle.
- Required fix: insert a 36C route-plan/role execution layer ahead of provider calls while retaining current OpenAI path as a rollback-compatible provider adapter until parity is proven.
- Regression prevention: deterministic multi-provider role plan, per-project provider-policy isolation, provider outage with approved fallback, no-fallback policy, local-only route, exact provider/model/cost evidence and concurrent projects choosing different plans.

### P36-0012 — Static catalog model aliases and scores are not authoritative live routing evidence

- Batch: 36C.
- Environment: provider catalog/technology inventory; production untouched.
- Symptom: many provider capabilities use model=`default` plus static cost/quality/latency/privacy values. This is adequate for historical routing tests but cannot truthfully prove that a specific current provider model exists, is enabled for the account, has the assumed price/context/capability or satisfies live policy.
- User impact: none yet because ProjectExecution does not consume this catalog. Using it unchanged in 36C could select a placeholder or make inaccurate cost/quality decisions.
- Root cause: the catalog was designed as a provider-independent capability abstraction, while durable provider runtime/model validation evolved separately.
- Required fix: construct a validated runtime capability snapshot from approved provider/model configuration and provider-specific model evidence; preserve deterministic test fixtures separately from live metadata; route only against validated models.
- Regression prevention: no `default` placeholder may be treated as live evidence; stale/unavailable models are excluded; cost/limits are versioned/auditable; provider-specific contract tests cover supported wire protocols before live routing.

### 36C protected baseline merge checkpoint — 2026-08-17

- Baseline PR #394 merged into `main` as `918c846fd18838c7cbd77d1f3e3d5d2d4b4385ee` after all required protected checks passed: Backend Tests, Production Docker Build, Browser boundaries, Frontend Build, CodeQL, repository secret/hygiene, SBOM, Dependency Security, Core contracts and Phase 36 Reporting.
- Fresh baseline evidence retained: provider/routing `21/21 PASS`; Phase 29J provider/model/synthetic contracts `45/45 PASS`; Phase 29F tenant-scoped knowledge/memory `4/4 PASS` on disposable PostgreSQL 16; Phase 36 root `15/15 PASS`; staged/commit reporting and secret/diff checks PASS.
- Production boundary remains unchanged by the baseline: zero live provider calls/spend, zero schema mutations, zero service restarts, and no ProjectExecution job was created. Provider inventory remains 13 connected + 2 configured AI providers; Azure OpenAI/AWS Bedrock are not claimed connected.
- Maturity remains unchanged: `multi-provider-project-routing=source_built`, `tenant-agent-memory-isolation=source_built`, Batch 36C=`in_progress`.

### 36C next safe transition

The baseline/inventory/technology/security gate is now merged and closed. Stop here as a safe checkpoint. On resumption, create a fresh implementation branch from merged `main` and begin with the tenant-safe durable route-plan contract plus deterministic fake-provider execution; do not make a live provider request or production mutation until routing/isolation/audit/fallback/budget/rate-limit regressions are green and the permanent report is updated.

### 36C route-plan foundation checkpoint — 2026-08-17

- Source baseline: implementation branch starts from merged `main` `6704b5fba7b7fefa967b96d227993930f2cf4769` after protected baseline PRs #394/#395. Production remains untouched and had zero active ProjectExecution jobs before isolated development.
- New contract: `project_execution_routing.py` introduces immutable organization/workspace/project/execution scope, explicit tenant provider allow/deny policy, validated non-placeholder model capabilities, role/task route plans, bounded approved fallbacks, tenant budget ceilings and prompt-free audit evidence.
- P36-0012 prevention is enforced at construction: `model=default` is rejected as live runtime evidence. Route candidates carry explicit provider/model plus evidence references; test fixtures use named synthetic runtime models rather than catalog aliases.
- Privacy/isolation behavior: restricted Project AI tasks route only to validated local capabilities; remote providers are not emitted as fallbacks. Route evidence contains scope, task/role, provider/model, cost/score/reasons/evidence reference but excludes prompt and system prompt content.
- Deterministic acceptance adapter: execution accepts only explicitly injected transports, makes no network/provider call by default, proves primary failure -> approved fallback with exact attempted routes, and proves no-fallback policy fails closed. It is not the production durable provider resolver.
- Verification: new focused contract `7/7 PASS`; legacy provider/routing plus new contract `27/27 PASS`; focused Ruff PASS; Mypy PASS for the new service. Historical baseline evidence remains `21/21`, `45/45`, `4/4`, and Phase36 `15/15`.
- Maturity truthfulness: `multi-provider-project-routing` and `tenant-agent-memory-isolation` remain `source_built`. P36-0010 remains open for durable tenant resolution/shared distributed rate-budget-circuit state; P36-0011 remains open until ProjectExecution actually consumes the route plan; P36-0012 is only partially closed because live provider-specific model validation is still required.
- Production boundary: no schema migration, provider secret read, live provider call/spend, ProjectExecution job, service restart or production mutation occurs in this checkpoint.
- Next safe transition after protected merge: durable organization-scoped provider/model resolution + persistent route/audit evidence + shared quota/circuit/budget coordination, still using deterministic fake providers before any live-provider acceptance.

### 36C route-plan protected merge checkpoint — 2026-08-17

- Protected merge: route-plan foundation PR #396 merged into `main` as `0e9308c3f379cce86ca42eab53aa2c36c1364ca0`. Every required check passed, including Backend Tests, Production Docker Build, Browser boundaries, Frontend Build, CodeQL Python/JavaScript, repository secret/hygiene, SBOM, Dependency Security, Core contracts and Phase 36 Reporting.
- Retained implementation evidence: new contract `7/7 PASS`; legacy provider/routing plus new contract `27/27 PASS`; backend compile/Ruff PASS; Mypy PASS across `180` source files; Phase36 root `15/15 PASS`; added-line secret scan `0`.
- Production read-only confirmation after merge: Backend, both same-host Project Workers, PostgreSQL and Redis remained healthy; active ProjectExecution jobs remained `0`. The new route-plan module is not wired into live ProjectExecution and caused no provider call, spend, schema mutation, service restart or production deployment.
- Maturity remains intentionally unchanged: `multi-provider-project-routing=source_built`, `tenant-agent-memory-isolation=source_built`, Batch 36C=`in_progress`. A protected source contract alone is not runtime verification.
- Open gates remain P36-0010 durable tenant/provider resolution plus shared distributed quota/circuit/budget state, P36-0011 actual ProjectExecution route-plan integration, and the live-provider-validation remainder of P36-0012.
- Next safe implementation boundary: durable organization-scoped provider/model resolver -> persistent route/audit evidence -> shared rate/quota/circuit/budget coordination -> deterministic multi-worker fake-provider acceptance. Stop before live provider calls or production mutation until those gates are green and separately reported.

### 36C durable routing authority checkpoint — 2026-08-17

- Scope remains isolated from live ProjectExecution/provider execution. Added Alembic `20260817_0029` plus durable route-plan/task/attempt/budget records, `DurableProjectAIResolver`, `DurableProjectAIRouteStore`, Redis-backed `ProjectAISharedCoordinator`, and `DurableProjectAIAuthority`; Production schema remains `0028` and no service is restarted.
- Tenant/provider evidence boundary: resolver requires the exact ProjectExecution `organization/workspace/project/execution` scope, only organization-owned `connected` and enabled `AIProvider` rows, and current explicit `validated_models` entries. `model=default`, future-dated evidence and expired evidence cannot route. Duplicate connected rows claiming the same provider/model fail closed.
- Persistent evidence boundary: route plans/tasks/attempts and `AuditEvent` details are prompt-free; provider credentials are never read or stored. Provider record IDs/model/evidence refs and integer micro-USD estimates/spend are retained for audit. Plan creation is fingerprint-idempotent.
- Shared coordination boundary: Redis keys are SHA-256 digests of organization/provider/model scope plus opaque lease/finalization IDs; raw tenant/provider/model identifiers do not enter Redis keys. Server-time Lua scripts coordinate rate, concurrency and circuit state across independent authority instances; acquisition fails closed if Redis is unavailable, while bounded concurrency release is TTL-safe.
- Durable budget boundary: PostgreSQL row locking shares one micro-USD budget across Workers. Reservation blocks before provider execution when `spent + reserved + estimate` exceeds the execution limit. Result finalization is idempotent and cannot double-spend; actual spend is retained truthfully even when it would reveal an overrun.
- Verification: durable authority `8/8 PASS`; focused route-plan + durable authority `15/15 PASS`; current unified route-plan/durable/legacy-provider/shipped-head regression `32/32 PASS`; migration round-trip `0029 -> 0028 -> 0029` with route-table count `4 -> 0 -> 4`; full Backend static gate PASS with Mypy `181` files; fresh Full Backend `657 passed, 0 failed` in `106.59s` on PostgreSQL 16 + Redis 7 disposable. No connection exhaustion/deadlock/PANIC/FATAL and all durable route rows are cleaned after tests.
- P36-0010 status: **closed for source/isolated authority**; the organization boundary, durable audit/budget and shared cross-worker coordination now exist. Live ProjectExecution use is deliberately not claimed.
- P36-0011 status: **open**; `project_execution.py` remains the live OpenAI execution path and has not been wired to the durable route authority.
- P36-0012 status: **closed for source routing authority / live evidence pending**; placeholder/static catalog models are not accepted by the durable resolver, but real provider-specific validated model evidence must still be populated and live-verified before production routing.
- Maturity remains truthful: `multi-provider-project-routing=source_built` and `tenant-agent-memory-isolation=source_built`; no `locally_executed` maturity is claimed until ProjectExecution itself consumes this authority in an integrated deterministic cycle.

### 36C durable-authority protected merge / next safe transition

- Durable-authority PR #398 merged into `main` as `789b63c215f4ceeb613d13f08b707e9465536d39` after every required protected check passed, including Backend Tests, Production Docker Build, Browser boundaries, Frontend Build, CodeQL, repository secret/hygiene, SBOM, Dependency Security, Core contracts and Phase 36 Reporting.
- Production remains unchanged by this merge: schema `0029` is source-only/disposable evidence; live Production remains on schema `0028`, the accepted OpenAI ProjectExecution path remains active, and no provider call/spend or service restart is performed.
- Next safe implementation boundary: organization-scoped memory adapter + rollback-compatible ProjectExecution integration with deterministic fake providers. Before any production migration or live provider request, create a fresh backup/restore gate and prove integrated two-Worker tenant isolation, fallback, shared budget and failure behavior.

### 36C deterministic ProjectExecution integration checkpoint — 2026-08-17

- Source baseline: this integration branch starts from merged `main` `8342e42b51ef0a04d70a1671d16df496d8a97884` after durable-authority PR #398 and its merge-evidence/correction PRs #399/#400.
- Integration boundary: added `ProjectAIProjectMemoryAdapter` and `DeterministicProjectAIIntegrationRunner` without replacing the default Production `ProjectPlanningRunner`. The new runner implements the exact synchronous Worker `.run(...)` contract and is injected only by isolated tests at this checkpoint; no production feature flag, provider call or service restart is introduced.
- Memory isolation: every memory operation verifies exact `organization/workspace/project/execution` scope plus requester organization, uses existing durable `ScopedMemory(scope_type=project)`, and writes prompt-free `AuditEvent` metadata. Stored provider outcomes retain bounded `memory_note`, provider/model/evidence/cost/latency and a SHA-256 result digest; raw task prompts are not persisted by the adapter.
- Worker integration: real `ProjectExecutionWorker.claim/execute_claim/complete/fail` paths consume the deterministic runner. `complete()` now persists `summary.provider` when supplied; the legacy runner already returns OpenAI, so default/rollback behavior is unchanged. No-fallback failures continue through the existing `retry_queued` semantics.
- Multi-worker evidence: two simultaneous Workers for two organizations complete independent provider plans and cannot observe each other's project memory. A second test uses two projects in one organization sharing OpenAI concurrency `1`; one Worker holds OpenAI while the other observes shared Redis concurrency and selects approved Anthropic fallback. Both complete and their memories remain project-scoped.
- Integration verification: new foundation `6/6 PASS`; unified Phase36B worker + 36C route-plan/durable/integration + legacy ProjectExecution regression `43/43 PASS`; Backend compile/Ruff PASS; Mypy `182` source files PASS; fresh Full Backend at Alembic `0029` `662 passed, 1 skipped, 0 failed` in `115.48s`; Phase36 root `16/16 PASS`; complete AIOS Core `723/723 PASS` in `29.16s`; Backend public Phase36 snapshot `1/1 PASS`. Fresh PostgreSQL shows no connection exhaustion/deadlock/PANIC/FATAL and integration route/memory rows clean to zero.
- Test-harness note: one previously reused disposable PostgreSQL instance rejected its expected test credential during a chained rerun. It was destroyed and recreated from `postgres:16-alpine`, migrated from zero to `0029`, and all retained integration/full evidence above was produced on fresh disposable services. Production credentials/data were never involved.
- Maturity transition supported by evidence: `multi-provider-project-routing` and `tenant-agent-memory-isolation` advance from `source_built` to **`locally_executed`** only. They are not `runtime_verified`: Production remains on schema `0028` and the default live ProjectExecution runner remains the rollback-compatible OpenAI path.
- P36-0010 status: **closed through deterministic/local ProjectExecution integration**; durable organization scope, shared coordination, budget and project memory are exercised together.
- P36-0011 status: **deterministic/local integration closed; Production activation remains open**. The live default runner has intentionally not been switched.
- P36-0012 status: **source authority closed / live provider evidence pending**. Explicit validated non-placeholder models are mandatory, but real production model evidence and live protocol acceptance remain future gates.

### 36C integration-foundation next safe transition

Protected source merge first. After merge, stop before Production activation. The next transition requires a fresh production backup with restore smoke, explicit opt-in runner/feature control, controlled application of migration `0029`, provider-specific validated model evidence and bounded live acceptance. No live provider call or Production migration belongs to this integration-source PR.

### 36C deterministic ProjectExecution integration protected merge — 2026-08-17

- PR #401 merged into `main` as `451e2e40fd0d5bb790c884077090dac126bef8d9`; post-merge verification then confirmed every required protected check passed: Backend Tests, Production Docker Build, Browser boundaries, Frontend Build, CodeQL, repository secret/hygiene, SBOM, Dependency Security, Core contracts and Phase 36 Reporting.
- Protected source now contains organization/project-scoped Project AI memory, the deterministic injected ProjectExecution integration runner, Worker provider-summary persistence, durable routing authority/migration `0029`, shared Redis provider coordination and the local two-Worker integration regressions.
- Production boundary is deliberately unchanged: the live default runner remains `ProjectPlanningRunner`, Production Alembic remains `20260817_0028`, no provider credential/live provider request/provider spend was used by the integration phase, and no production service was rebuilt/restarted for PR #401.
- Retained maturity is `multi-provider-project-routing=locally_executed` and `tenant-agent-memory-isolation=locally_executed`; `runtime_verified` is not claimed because the opt-in Production path has not been activated.
- P36-0011 remains a Production activation gate only: the deterministic/local ProjectExecution path is proven, but switching the live default path still requires backup/restore, feature/runner rollback control, migration `0029`, current provider model evidence and bounded live acceptance.

### 36C pre-production activation safe stop

Source integration is merged and Production remains stable on the previous accepted runtime. Stop here before any activation. On resumption, first establish a fresh Production backup plus restore smoke and explicit rollback/runner-selection boundary; only after those gates may migration `0029` and controlled provider-specific live acceptance be considered.

### 36C integration merge-evidence protected closeout — 2026-08-17

- Merge-evidence PR #402 merged into `main` as `91fe417956c047dd68958d3400d89230abc1f434` after every required protected check passed, including Backend Tests, Production Docker Build, Browser boundaries, Frontend Build, CodeQL, repository secret/hygiene, SBOM, Dependency Security, Core contracts and Phase 36 Reporting.
- Final read-only Production safety snapshot after the source/report merges: Backend, both same-host Project Workers, PostgreSQL and Redis are healthy; Production Alembic remains `20260817_0028`; active ProjectExecution jobs are `0`; the running Backend still reports `current_batch=36C`.
- Capability maturity remains deliberately bounded at `multi-provider-project-routing=locally_executed` and `tenant-agent-memory-isolation=locally_executed`. No `runtime_verified` claim is made because migration `0029` and the deterministic multi-provider runner are not activated in Production.
- No backup, migration, build, service restart, provider credential read, live provider request or provider spend is performed in this checkpoint.
- Safe handoff: begin the next session from merged `main` only after recording this checkpoint branch. First establish a fresh Production backup plus disposable restore smoke and an explicit opt-in runner/rollback boundary. Do not apply migration `0029` or make a live provider call before those gates are green and reported.

### 36C production activation gate 1 — backup / restore — 2026-08-17

- Pre-production checkpoint PR #403 merged into `main` as `3f49e3e9889542afb02598cb6178288191db8024` after all protected checks passed. Production still ran the accepted legacy ProjectPlanningRunner path on Alembic `20260817_0028`, with Backend/two Project Workers/PostgreSQL/Redis healthy and active ProjectExecution jobs `0`.
- Fresh backup created outside Git at `/opt/AIOS/.deployment-backups/phase36c-production-activation/aios-20260817T115113Z.tar.gz`, size `6885750` bytes, SHA-256 `bb75913df3c38962e698fd46c886260ed8cdfaf2b0a3806b5e7d498042d8da3`. The plaintext SQL was removed by the backup script after archive creation.
- Backup verification: sidecar checksum matched, archive paths were safe, and exactly one `aios-*.sql` entry was present.
- Disposable restore smoke: restored into fresh PostgreSQL 16 without touching Production. Restored state matched the pre-migration Production snapshot exactly: Alembic `0028`, ProjectExecutions `1`, AI providers `15`, backup records `13`, organizations `2`. Disposable restore infrastructure was removed after verification.
- Production remained unchanged after the smoke: schema `0028`, active ProjectExecution jobs `0`, and all core services healthy. No provider credential was read and no live provider request/spend occurred.
- Gate result: **PASS**. Migration `0029` remains blocked until an explicit opt-in production runner/rollback boundary is merged and protected while the legacy OpenAI runner remains default.

### 36C production activation gate 2 — next safe boundary

Implement the production runner selector as an explicit opt-in with a fail-closed multi-provider mode and immediate rollback to the existing `ProjectPlanningRunner`. Test default-off behavior, missing/invalid configuration, schema compatibility, and deterministic injected-provider selection without live provider calls. Merge and protect that source boundary before applying migration `0029`.

### 36C production activation gate 2 — explicit runner / rollback boundary — 2026-08-17

- Gate 1 evidence is protected through backup/restore PR #404 merged as `11651979c9779305d300c2bdf385419512d1ae1d`; Production remains healthy on Alembic `0028` with zero active ProjectExecution jobs.
- Added `PROJECT_EXECUTION_RUNNER_MODE` with allowed modes `legacy|phase36c` and default `legacy`. Both Production Compose sources pin `PROJECT_EXECUTION_RUNNER_MODE: legacy` explicitly, so an env-file-only change cannot silently activate multi-provider execution.
- `resolve_project_execution_runner()` preserves `ProjectPlanningRunner` for `legacy`, rejects unknown modes, and fails closed for `phase36c` unless a validated runner is explicitly injected by a later activation layer. `ProjectExecutionWorker` and its healthcheck use this selector when no runner is injected; deterministic tests may continue to inject the Phase36C runner directly without changing Production defaults.
- Rollback boundary: the live/default runner remains the existing legacy OpenAI path; rollback is the explicit `legacy` selection and requires no schema downgrade. Gate 2 itself does not restart services, modify the Production env file, query the new `0029` tables from Production, or call a provider.
- P36-0013: an older integration test asserted the literal source text `runner or ProjectPlanningRunner()`. Gate 2 replaced that implementation with a selector while preserving behavior, so the stale text assertion failed once. It was corrected to assert the selector-based legacy boundary; no runtime code was reverted to satisfy the obsolete source string.
- Verification: runner-selector `5/5 PASS`; unified selector + Phase36B worker + route-plan/durable/integration/legacy ProjectExecution regression `48/48 PASS`; Backend Ruff PASS; Mypy `182` source files PASS; both Production Compose sources parse; fresh Full Backend at Alembic `0029` `667 passed, 1 skipped, 0 failed` in `110.84s`. Disposable route/task/attempt/budget/active-execution counts clean to zero and PostgreSQL/Redis critical log hits are zero.
- Production boundary remains unchanged after tests: live schema `0028`, Backend/two Project Workers/PostgreSQL/Redis healthy, active ProjectExecution jobs `0`.

### 36C production activation gate 2 — next safe transition

Gate 2 is open as PR #405; merge it only after every protected check is green. After merge, re-confirm the fresh backup artifact/checksum and zero active jobs, then apply migration `0029` only. Keep the Production runner pinned to `legacy` during schema migration and post-migration acceptance. Provider-specific model evidence and live provider activation remain separate later gates.

### 36C pre-migration Production checkpoint — 2026-08-17

- Gate 2 PR #405 merged into `main` as `c01ce06770bac00897673664e47dbd406201eeaf` after all protected checks passed. Production remained healthy on Alembic `0028` with zero active ProjectExecution jobs.
- Fresh backup gate remains valid: `/opt/AIOS/.deployment-backups/phase36c-production-activation/aios-20260817T115113Z.tar.gz`; SHA-256 re-verification PASS. Disposable restore smoke previously matched Production exactly.
- Pre-change rollback images are pinned: `aionex-aios-backend:pre-phase36c-20260817T115113Z` -> `sha256:9eaf7b862d52a1733274481316bcb63fac922fccecc4239ebf9cae6bf7c70ebb`; `aionex-aios-project-worker:pre-phase36c-20260817T115113Z` -> `sha256:f0dd66a7790614499fd14674e936a4ce6c118c4b1c332586be17942d8475d531`.
- Candidate images built from merged main: Backend `sha256:438bf7817b7740aa5ee97aba256979da834a16669c95639dbec03a5af26b7797`; Project Worker `sha256:73e54cb8053e8cdefb5af91edbb966bef99a23a23d6048891921a46e1c4c43fc`. Running containers still use the rollback image IDs at this checkpoint.
- One-off validation: Backend candidate ships Alembic head `0029` and reads Production current `0028`; Project Worker candidate reads `PROJECT_EXECUTION_RUNNER_MODE=legacy` and its healthcheck exits `0` against the current Production dependencies.
- Migration safety boundary: apply only `0028 -> 0029`, then immediately recreate Backend and both Project Workers on the candidate images. Keep runner mode pinned `legacy`; do not populate validated models, switch runner mode, call a live provider, or spend provider budget in this migration gate.

### 36C production activation gate 3 — schema / legacy-runtime activation — 2026-08-17

- Gate 2 PR #405 merged as `c01ce06770bac00897673664e47dbd406201eeaf`. Fresh backup checksum was re-verified and active ProjectExecution jobs remained `0` immediately before the Production change.
- Pre-change rollback tags: Backend `aionex-aios-backend:pre-phase36c-20260817T115113Z` -> `sha256:9eaf7b862d52a1733274481316bcb63fac922fccecc4239ebf9cae6bf7c70ebb`; Project Worker `aionex-aios-project-worker:pre-phase36c-20260817T115113Z` -> `sha256:f0dd66a7790614499fd14674e936a4ce6c118c4b1c332586be17942d8475d531`.
- Merged candidate images were built before migration: Backend `sha256:438bf7817b7740aa5ee97aba256979da834a16669c95639dbec03a5af26b7797`; Project Worker `sha256:73e54cb8053e8cdefb5af91edbb966bef99a23a23d6048891921a46e1c4c43fc`. One-off validation proved Backend shipped head `0029` while Production was `0028`, and Worker candidate reported runner mode `legacy` with healthcheck PASS.
- Production migration `20260817_0028 -> 20260817_0029` completed successfully. Post-migration invariants: four Project-AI route tables present, historical ProjectExecutions remained `1`, active jobs `0`, AI providers remained `15`.
- Backend was recreated alone on the new image and became healthy with `/ready=ready` and Alembic `0029`. Both Project Workers were then recreated using the existing Phase36B scale override; both are healthy on the new image, both report `PROJECT_EXECUTION_RUNNER_MODE=legacy`, and durable registry reports `online=2`, total capacity `4`, active `0`.
- Live Project-AI state remains dormant by design: plans/tasks/attempts/budgets `0`, Redis `aionex:project-ai:*` keys `0`, active ProjectExecution jobs `0`. No provider credential was read and no live provider request/spend occurred.
- Live ingress acceptance: `vip-e.net`, `ai.vip-e.net/en/`, `api.vip-e.net/ready`, and `gabarot.vip-e.net` returned HTTP 200. Twenty API ready requests were 20/20 HTTP 200 with p50 `107.3ms`, p95 `147.4ms`, max `178.3ms`.
- Backend/Worker/Redis critical logs since recreate were zero. PostgreSQL FATAL lines were exclusively the previously documented P36-0008 `role "root" does not exist` healthcheck noise from the old PostgreSQL container; no deadlock, connection exhaustion, PANIC or application database failure was observed. PostgreSQL was not restarted solely for that known logging defect.
- Maturity remains `locally_executed`, not `runtime_verified`: Production now has the schema and rollback boundary, but the live runner is intentionally still `legacy` and no provider-specific live route has executed.

### 36C production activation gate 3 — next safe transition

Keep Production runner mode `legacy`. Inventory provider records without reading credentials; determine which connected providers already have current explicit non-placeholder `validated_models` evidence. Add/verify provider-specific model evidence and real invocation adapters/error mapping under protected tests. Only then perform tightly bounded live-provider acceptance before considering a `phase36c` runner switch.

### P36-0014 — Production provider rows have no validated model evidence

- Batch: 36C provider-evidence gate.
- Production inventory, non-secret: all 15 AI provider rows currently report zero `validated_models`; 13 remain connected and Azure OpenAI/AWS Bedrock configured. Provider credentials are server/environment sourced and were not read or printed by this inventory.
- Root cause: the Phase29J runtime can probe authenticated model inventories for supported providers, but its historical `provider_health_probe()` retains only endpoint status/latency and discards model IDs. Anthropic, Cohere and AWS Bedrock intentionally use execution as authoritative live verification instead of claiming a model-listing proof.
- Risk if ignored: enabling the Phase36C runner would fail closed because `DurableProjectAIResolver` correctly requires current explicit validated-model evidence; manufacturing entries from the static capability catalogue would create false model/pricing/capability claims.
- Source fix: `provider_model_evidence.py` introduces provider-specific inventory parsing/probing, explicit inventory and execution evidence types, reviewed `ProviderModelValidationSpec`, stale/future/default rejection, bounded TTL and tenant-scoped idempotent persistence. Static catalogue aliases/scores are never transformed into live evidence automatically.
- Security boundary: tests inject the inventory requester and synthetic credential resolution; no real network/provider call occurs. Durable evidence contains provider/model/evidence/policy/capability/rate/cost metadata only, never credential values or prompts.
- Verification: focused `6/6 PASS`; evidence/routing/durable/integration/runner/Phase29J regression `39/39 PASS`; Backend Ruff PASS; Mypy `183` source files PASS; fresh Full Backend at `0029` `673 passed, 1 skipped, 0 failed` in `110.26s`; disposable Project-AI rows cleaned to zero and PostgreSQL/Redis critical logs were zero.
- Status: **source gate implemented, live evidence still absent**. Production remains `PROJECT_EXECUTION_RUNNER_MODE=legacy`; all 15 provider rows still have zero validated models and no live provider request/spend has been performed by this gate.

### 36C provider-evidence next safe transition

Provider-model evidence source is open as PR #407; merge it only after every protected check is green. After merge, keep the runner on `legacy` and probe inventory-capable providers one at a time with read-only model-list requests. Persist a model only when it is present in fresh inventory and an explicit reviewed capability/pricing/rate policy exists. Anthropic/Cohere/AWS Bedrock require bounded execution receipts rather than inventory claims. Live ProjectExecution activation remains blocked.

### 36C pre-live provider inventory checkpoint — 2026-08-17

- Provider-model evidence PR #407 merged into `main` as `36fcee5e001ccfc08123f1b0a6f97627229b81ef` after all protected checks passed. No live provider request occurred before this checkpoint.
- Production guard immediately after merge: Backend/two Project Workers/PostgreSQL/Redis healthy, Alembic `0029`, both Workers runner mode `legacy`, active ProjectExecution jobs `0`, providers with any `validated_models` `0`.
- Allowed next action is inventory-only and one provider at a time. Connected inventory-capable providers: OpenAI, Gemini, OpenRouter, Ollama, Mistral, xAI, DeepSeek, Groq, Together, Fireworks and Hugging Face. Azure OpenAI is configured rather than connected and will not be probed at this gate.
- Anthropic, Cohere and AWS Bedrock remain execution-evidence providers and must not be represented as model-inventory validated. No live execution belongs to this inventory gate.
- Inventory responses may be used to prove model existence only. No model is persisted to `validated_models` until a separate explicit reviewed `ProviderModelValidationSpec` supplies tasks, capabilities, pricing, rate/concurrency limits and evidence TTL. Static catalogue aliases/scores remain prohibited as live proof.
- Runner activation remains blocked: keep `PROJECT_EXECUTION_RUNNER_MODE=legacy`; no ProjectExecution is allowed onto the Phase36C runner during inventory probing.

### 36C live provider inventory evidence — 2026-08-17

- Preconditions: provider-evidence PR #407 merged as `36fcee5e001ccfc08123f1b0a6f97627229b81ef`; Production healthy on Alembic `0029`; two Project Workers explicitly `legacy`; active ProjectExecution jobs `0`; persisted validated-model providers `0`.
- Inventory-only probes were executed sequentially and never as generation/jobs. No provider row was written, no prompt was sent and no execution/spend was requested. Evidence JSON is retained outside Git at `/opt/AIOS/.deployment-backups/phase36c-provider-inventory/`.
- Successful current inventory counts: OpenAI `124`, Gemini `50`, OpenRouter `414`, Ollama `1` (`gemma3:4b`), Mistral `55`, xAI `12`, DeepSeek `2`, Groq `13`, Together `281`, Fireworks `24`, Hugging Face `136`. Gemini returned 50 models and explicitly no further page indicator in the live response.
- Aggregate inventory evidence SHA-256: `71d04d52ce62f0e12d0489dca14d75ca4c03874214b7785ed3b826ec63b1b3cb`. Per-provider evidence refs and file hashes are retained in `inventory-summary.json` outside Git.
- Intentional exclusions: Anthropic, Cohere and AWS Bedrock require bounded execution evidence instead of an inventory claim; Azure OpenAI is configured but not connected and was not probed.
- Drift evidence already observed: historical completed Groq job model `llama-3.1-8b-instant` is not in the current Groq model inventory, proving historical jobs/static catalogues cannot be used as current routing evidence.
- Post-probe Production guard: active ProjectExecution jobs `0`, both Workers `legacy`, providers with persisted `validated_models` `0`. Inventory proves model existence only and does not itself authorize routing.

### 36C validated-model policy next safe transition

Create an explicit reviewed initial model policy from the fresh inventories and authoritative provider capability/pricing/rate documentation. Use conservative limits and keep policy metadata separate from inventory proof. Persist only models that satisfy both fresh existence evidence and the reviewed policy. Do not switch Production runner mode; bounded provider invocation acceptance remains required after persistence and before Phase36C runtime activation.

### 36C Launch-100 readiness foundation — 2026-08-17

- Launch target is now explicit: the first public release must admit at least **100 simultaneous users/project submissions durably** under tenant-fair queueing/backpressure, while retaining the already proven 1000-admission architecture as the future scale envelope. This target does not claim 100 CPU-heavy project builds execute in parallel on one host; execution concurrency remains bounded by worker/provider capacity while every accepted job is durable, isolated and observable.
- Access policy foundation: Free users default to the local zero-provider-cost route `ollama:gemma3:4b`; paid users fail closed until the Owner selects current validated provider/model pairs; per-user Owner overrides take precedence over plan defaults. Provider/model consumption never comes from client input alone.
- Platform-provider isolation: provider credentials remain owned by the platform provider pool organization `aionex-org`. Consumer tenants may resolve a platform provider only through explicit Owner access policy. Resolver filtering is exact `provider:model`; credentials are not copied into tenant rows. Duplicate provider/model claims still fail closed.
- Owner control surface source: Project-AI Owner API exposes Free/Paid policy, per-user overrides, safe validated-model metadata and provider-finance policy without returning credentials. Owner Dashboard contract has been extended for the new routes.
- Provider-finance foundation: Owner-configured funded credit/low/critical thresholds live in `OwnerControlRecord`. Consumption is calculated from durable Project-AI `actual_microusd` plus AI-agent runtime spend. OperationsObserver periodically emits Owner warning/critical notifications using the existing in-app + protected external-channel policy; billing/quota failures can escalate immediately without persisting provider error payloads.
- Model freshness rule: static catalogue aliases and historical job models remain prohibited as live routing authority. OpenAI's current official generation is GPT-5.6, but the current project credential's authenticated `/v1/models` evidence did not expose GPT-5.6 model IDs at the inventory checkpoint. Therefore the Owner UI/policy may record the desired-current family, but runtime activation must use only model IDs actually present in fresh credential-specific inventory/execution evidence; unavailable current models generate an Owner action item instead of silently falling back to stale models.
- Test findings before final Full Backend rerun: Launch/finance focused contracts pass, Owner route contract was updated, and a Launch test fixture that left a queued `ProjectExecution` polluted later Worker tests. The fixture was converted to completed evidence state; focused rerun on a fresh disposable DB proved the old Worker tests and Launch/finance contracts pass. Final fresh Full Backend rerun remains required before this foundation is protected/merged.
- Maturity remains unchanged at `locally_executed`; Production remains Alembic `0029`, Project Workers remain `legacy`, and no multi-provider ProjectExecution activation is claimed.

### 36C Launch-100 PR #409 correction / current-model policy checkpoint — 2026-08-17

- PR #409 exposed one stale Owner navigation source contract after `/owner/project-ai` increased Owner pages from 46 to 47. The contract was corrected and passes locally.
- Fresh isolated Full Backend after the correction: `691 passed, 1 skipped, 0 failed` in `177.46s`.
- Current launch-model evidence now combines reviewed official policy with credential-specific inventory existence: OpenAI GPT-5.6 Sol/Terra/Luna, Mistral Medium 3.5 and DeepSeek V4 Pro are present in retained live inventories. Static aliases/history remain prohibited as routing evidence.
- Focused launch-model/access/integration/navigation regression: `19/19 PASS`; model-policy tests `4/4 PASS`; focused Ruff/Mypy PASS.
- Production remains untouched by this checkpoint: Alembic `0029`, Project Workers `legacy`; no validated-model persistence and no Phase36C runner activation.

### 36C Launch-100 remaining gates

1. Protect/merge Launch access, Owner policy and provider-finance source after fresh Full Backend + frontend/owner UI gates.
2. Persist reviewed current validated model evidence for an initial launch set. Free must remain local/free; paid models require fresh provider evidence, reviewed capability/pricing/rate policy and Owner selection.
3. Add the production Phase36C invoker factory/error mapping that consumes only Owner-authorized validated models; keep the rollback selector `legacy` until bounded live acceptance passes.
4. Run bounded live invocation acceptance provider-by-provider (Anthropic/Cohere/AWS Bedrock require execution evidence; Azure OpenAI remains gated until connected).
5. Prove Owner provider credit/low-balance alerts end-to-end through the configured Owner notification channels and prove 402/429/billing failures generate deduped escalation.
6. Prove Launch-100 with at least 100 isolated user/tenant project submissions, no loss/duplication, fair queueing, correct Free/Paid/User routing policy, bounded provider concurrency/budget/circuit behavior and no cross-tenant memory/provider access.
7. Execute controlled Production Phase36C canary, then two-Worker live route/fallback/memory acceptance. Only after these are green may `PROJECT_EXECUTION_RUNNER_MODE=phase36c` be considered for the launch population and maturity advance to `runtime_verified`.

### 36C Launch-100 Owner control UI checkpoint — 2026-08-17

- Owner Project-AI snapshot now includes up to 1000 active managed users with only safe display fields: user id/name/email, organization id/name, effective plan/access class and override-active flag. Password hashes, provider credentials and secret fields are never returned.
- New Owner page `/owner/project-ai` is wired into Owner navigation and the Owner dashboard. It controls Free/Paid plan policy, per-user override, safe validated model selection and provider funded-credit/low/critical thresholds. The UI does not accept arbitrary live model IDs; selection is limited to backend-returned validated models, while desired-but-not-yet-validated policy entries are shown as awaiting evidence.
- Frontend verification: TypeScript PASS, ESLint PASS, Owner Arabic coverage PASS with `963` translatable strings and `5` approved technical tokens, Prettier PASS, production Next.js build PASS with `87/87` static pages including `/owner/project-ai`.
- Backend/UI contract verification after safe-user snapshot: Launch/finance contracts `13/13 PASS`; Owner route registration and client-to-route coverage PASS.
- Production remains untouched by this UI checkpoint: Alembic `0029`, Project Workers remain `legacy`; no provider-model evidence persistence, runner activation or provider spend occurs.

### 36C Launch-100 durable acceptance — 2026-08-17

- A dedicated acceptance test creates **100 independent organizations/users/projects/executions** against one protected platform provider pool. Policy split is 50 Free -> local Ollama, 40 Paid -> Owner Paid default, 10 Paid -> per-user Owner override. Invokers are deterministic/fake so the test proves routing, queueing, memory and accounting without network traffic or spend.
- Four-slot baseline: `100/100` completed with 4 bounded Workers; elapsed `60.928s`, completion p50 `31.202s`, p95 `58.301s`, max `60.322s`. Exactly 50/40/10 executions persisted the expected provider class, 100 project-scoped memories remained tenant-isolated, 100 route attempts were recorded, and no queued/running execution remained.
- Six-slot launch-shape run: `100/100` completed with 6 bounded Workers; elapsed `60.226s`, completion p50 `32.372s`, p95 `58.096s`, max `59.699s`; routing/isolation/accounting assertions remained identical. The small delta versus 4 slots proves same-host Worker count is not the dominant synthetic bottleneck, so scaling beyond the conservative launch shape is not justified by this evidence alone.
- Source-only launch scale override `deploy/phase36c/docker-compose.project-worker-launch100.yml` defines 3 replicas with capacity 2 each (6 slots). It is **not deployed yet**. Host capacity is 12 CPUs / 62 GiB RAM; keeping the launch shape at three Workers preserves headroom for Backend/PostgreSQL/Redis and other services.
- Launch claim is intentionally precise: 100 simultaneous users/project submissions can be accepted and drained durably under bounded workers with no loss, duplication or cross-tenant memory/provider access. This does not claim 100 CPU-heavy builds execute simultaneously on one host. The 1000-admission architecture remains the future scale envelope.

### 36C Launch-100 acceptance checkpoint — 2026-08-17

- Protected-source branch: `phase36c/launch-100-readiness`; Launch foundation commits `1fb1387` (access/provider-finance), `43b3948` (Owner Project-AI controls) and `17c602a` (Launch-100 acceptance test). PR #409 is open against `main`; Production is not changed by this PR and remains Alembic `0029` with both Project Workers in `legacy` runner mode.
- Isolated Launch-100 acceptance PASS: `100` users / `100` organizations / `100` projects admitted and completed through `4` bounded Project Workers. Routing distribution was `50` Free -> `ollama:gemma3:4b`, `40` Paid -> Mistral test route, `10` Owner override -> DeepSeek test route. No queued/running execution remained after drain; exactly `100` durable route attempts and `100` project-scoped memory records were verified with unique tenant/project scope.
- Timing evidence: elapsed `60.527s`; completion p50 `31.376s`, p95 `57.990s`, max `59.910s`. This is isolated deterministic launch evidence, not a claim of 100 simultaneous external-provider generations. The production design keeps execution concurrency bounded while durable admission/queueing supports the launch population.
- The acceptance test is deterministic/fake-provider only. It proves tenant isolation, Free/Paid/Owner-override routing, bounded four-worker drain, durable attempt accounting and memory isolation without provider spend. Live-provider acceptance and production runner activation remain separate gates.
- Current safe next action: let PR #409 pass all protected checks. After merge, run a fresh Full Backend/Frontend regression from merged `main`, then continue with reviewed/persisted current model evidence, production invoker/error mapping, provider-credit alert end-to-end proof and bounded live-provider acceptance. Do not switch Production from `legacy` before those gates are green.

### 36C current-model live-runtime refresh checkpoint — 2026-08-17

- Credential-specific OpenAI re-probe from the running Backend returned 124 model IDs and directly confirmed `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna` are currently available to the project credential. The earlier absence checkpoint remains historical evidence of why credential-specific freshness is mandatory; no stale GPT mini/nano model is promoted as a substitute.
- Reviewed launch model policy is now explicit and evidence-gated: Free `ollama:gemma3:4b`; Paid choices include current OpenAI GPT-5.6 Sol/Terra/Luna, Mistral `mistral-medium-3-5`, and DeepSeek `deepseek-v4-pro`. Mistral/DeepSeek/OpenAI pricing/context/capability policy is versioned separately from model-existence evidence; internal routing scores and concurrency caps are conservative platform policy, not provider benchmark/limit claims.
- Live runtime source remains double-armed and dormant: `PROJECT_EXECUTION_RUNNER_MODE=phase36c` alone is insufficient; `PROJECT_AI_LIVE_RUNTIME_ENABLED=true` is also required unless a test runner is injected. Both production Compose sources remain pinned `legacy` plus live-runtime disabled.
- Generic live invoker reuses the existing Phase29J provider transport implementation, verifies exact provider/model/evidence TTL before request, computes cost from validated model pricing, maps provider billing/quota/auth/transport failures to stable redacted codes, and routes billing/quota signals into the existing Owner notification system. Focused live-runtime/model-policy/boundary/access regression is `27/27 PASS`; Ruff/Mypy focused checks PASS.
- Manual current-model refresh is exposed only to Super Owner at `POST /api/v1/owner/project-ai/models/refresh`. Refresh probes reviewed launch providers, persists only models present in successful current inventory, immediately revokes an exact launch model if a successful inventory proves it disappeared, and preserves old unexpired evidence across transient probe failure. Evidence TTL is 6 hours. Refresh contracts `3/3 PASS`.
- Owner `/owner/project-ai` now has a model-evidence refresh action. Backend route/client contracts plus refresh tests pass; TypeScript PASS, ESLint zero warnings, Arabic coverage `965/5`, Prettier PASS, production frontend build `87/87`.
- Production is still unchanged by this checkpoint: Alembic `0029`, live Project Workers remain `legacy`, and no Phase36C ProjectExecution provider generation/spend has been enabled.

### 36C automatic current-model refresh source checkpoint — 2026-08-17

- Automatic launch-model evidence refresh is implemented in `OperationsObserver` but remains **disabled by default**. `PROJECT_AI_MODEL_REFRESH_ENABLED=false` is pinned in both Production Compose sources; refresh interval defaults to 4 hours and is bounded from 15 minutes to 24 hours.
- When explicitly enabled later, a due observer cycle runs `refresh_launch_model_evidence()` in its own committed DB session, publishes only returned Owner notifications, and records the refresh monotonic timestamp so the next cycle cannot duplicate work before the interval.
- Scheduler/observer regression is `10/10 PASS`; focused Ruff/Mypy PASS. Production has not enabled automatic provider inventory calls in this checkpoint.
- P36-0015 launch cleanup gate: legacy ProjectExecution Compose still carries `PROJECT_EXECUTION_RESEARCH_MODEL=gpt-5.4-nano`. Phase36C live routing does not use this legacy setting, but the launch cannot be declared current-model-clean while any active rollback path is configured to an obsolete model. Before final launch activation, replace the legacy OpenAI research model with a current credential-proven GPT-5.6 model and prove the legacy rollback path still passes its retained tests.

### 36C PR #409 merge + legacy current-model safety checkpoint — 2026-08-17T15:55:25Z

- PR #409 (`Phase 36C Launch-100 readiness foundation`) merged to `main` as `5236bd6c7009e7b1c11494721b4d8e758aee75a3` after every protected PR check was green. Fresh post-merge checks on the merge commit finished `14/14 SUCCESS`; one Python CodeQL attempt failed only because GitHub action download/API returned external `429/503`, the failed job was rerun, and the rerun passed. Production Docker Build, Backend Tests, Frontend, Browser, SBOM, secrets, dependency security, CodeQL and Phase36 reporting all passed on merged `main`.
- Production was explicitly rechecked after the merge: Alembic remains `20260817_0029`, Backend and both Project Workers are healthy, both Workers remain `PROJECT_EXECUTION_RUNNER_MODE=legacy`, and active queued/running/retry ProjectExecution count is `0`. The merge did not deploy or arm Phase36C live routing.
- P36-0015 legacy rollback/current-model source closure is now prepared on `phase36c/live-runtime-wip`: legacy planning and research defaults move from stale GPT-5 mini/nano identifiers to credential-proven `gpt-5.6-luna`; operator examples and both production Compose definitions agree on the same current model. Free-plan full project generation now fails closed while `phase36c` + the local/free live runtime are not explicitly armed, preventing Free users from falling through the remote legacy OpenAI path.
- Current OpenAI pricing was re-reviewed against the July 30, 2026 official API price reduction. Launch policy is bumped to `phase36c-launch100-model-policy-v2`; current policy values are Sol `5/30`, Terra `2/12`, Luna `0.20/1.20` USD per million input/output tokens. Because Luna's current price keeps the governed worst-case legacy cycle below the existing `$0.05` cap, the attempted `$0.15` legacy cap expansion was removed; the historical five-cent spend ceiling is retained instead of increasing Production risk. Sources: https://openai.com/api/ ; https://openai.com/index/advancing-the-price-performance-frontier-with-gpt-5-6/ ; https://openai.com/products/release-notes/ .
- Safety rollback evidence: the pre-correction dirty working diff was retained outside Git at `.deployment-backups/phase36c-legacy-model-refresh/pre-fix-b2246bf.patch`, SHA-256 `5a73d14cf8a2898460bf12e1927beca4462b94fe8cec4d324a5e81674380c864`.
- Verification on disposable PostgreSQL 16 + Redis 7: complete `test_project_execution_runtime.py` is `16/16 PASS`; launch-model policy + model-refresh suites are `7/7 PASS`; earlier focused combined gate is `11/11 PASS`; focused Ruff PASS; focused Mypy PASS (`4` source files); both production Compose configurations parse successfully; `git diff --check` PASS. No Production database/provider row, provider credential, runner mode, or provider call/spend was changed by these tests.
- Protected PR #410 first CodeQL scan found two high-severity test-only URL-sanitization alerts in the injected model-inventory requester because test routing used raw domain substring checks. The helper now parses URLs with `urlsplit` and matches exact provider hostnames/path, eliminating ambiguous-host acceptance; model-refresh regression is `3/3 PASS` and Ruff PASS after the fix. This finding did not expose a Production credential or change provider routing, but it is treated as a blocking source gate until the rerun is green.
- What remains: protect this current-model/Free-fail-closed source checkpoint in Git and let protected CI run before any deployment. After source protection, refresh/persist only Owner-reviewed fresh model evidence, complete production invoker/error mapping and provider-credit alert proof, then run bounded live-provider acceptance. `PROJECT_EXECUTION_RUNNER_MODE=phase36c` and `PROJECT_AI_LIVE_RUNTIME_ENABLED=true` remain prohibited until those gates are green.
- Safe point: PR #409 and merged-main validation are closed and green; Production stays `0029 + legacy`; the next write is source protection only, not Production activation.

### 36C PR #410 protected merge checkpoint — 2026-08-17T16:12:57Z

- PR #410 `Phase 36C current-model live-runtime safety gate` merged to `main` as `58694f7fb68627ec50783039e0f098fbc94b0434` after the final head `070e338ceb1740cbf151f107f790fbb9fdd66b9f` completed every protected gate with no failures or pending jobs. Green evidence included Backend Tests, Production Docker Build (including legacy DATABASE_URL upgrade, bare Compose legacy-env compatibility, and backup/restore round-trip smoke), Backend SBOM/vulnerability, both CodeQL analyses plus PR CodeQL, Browser boundaries, Owner/VIP frontend gates, Policy/Resilience, repository secret hygiene, Core Owner/Release/Web contracts, Dependency Security, Nginx Docker DNS and Phase 36 Reporting Invariant.
- The first PR #410 CodeQL alert was test-only URL matching in model-refresh fixtures. It was fixed with parsed exact-host/path matching, re-tested locally (`3/3` model-refresh focused; Phase36 reporting `10/10`) and the protected rerun completed green. No Production credential or provider payload was exposed.
- P36-0015 is now **source-closed but deployment-pending**: merged source and production examples use credential-proven `gpt-5.6-luna` for the legacy planning/research rollback path and add the Free-plan fail-closed guard. The currently running Production containers have deliberately not been recreated yet; both healthy Project Workers still report `PROJECT_EXECUTION_RUNNER_MODE=legacy` and still carry the pre-deployment `PROJECT_EXECUTION_RESEARCH_MODEL=gpt-5.4-nano`. Production schema remains Alembic `20260817_0029`; active queued/running/retry ProjectExecutions were `0` at this checkpoint.
- No Phase36C live runtime, automatic model refresh, provider generation or paid-user live route was activated by this merge. The safe next transition is a controlled deployment of the merged current-model rollback source with pre/post health and rollback evidence while keeping `legacy` + live-runtime disabled; only after that may reviewed validated-model persistence, production invoker/error mapping, provider-credit alert proof and bounded live-provider acceptance proceed.
- Current safety boundary: do not set `PROJECT_EXECUTION_RUNNER_MODE=phase36c`, do not set `PROJECT_AI_LIVE_RUNTIME_ENABLED=true`, and do not persist or route models merely from static catalogue policy. Fresh Owner-reviewed credential-specific evidence remains mandatory.
### 36C PR #410 production deployment evidence — 2026-08-17T16:31:48Z

- Protected documentation PR #411 merged to `main` as `014066582d45ce7219d8e8e5b69e4a5e364ee937` after every protected check completed green. Production deployment then used the already-merged PR #410 runtime source (`070e338ceb1740cbf151f107f790fbb9fdd66b9f`); the only differences to current `main` were the two documentation files from PR #411.
- Pre-deploy data safety: fresh Production PostgreSQL backup `/opt/AIOS/.deployment-backups/phase36c-pr410-deploy/aios-20260817T162455Z.tar.gz`, SHA-256 `3cea95f5de98e11543c0213cf9ca8330f4b8895bf2ec81340caae63c23696e67`. Disposable PostgreSQL 16 restore smoke PASS: Alembic `20260817_0029`, `project_executions=1`, `ai_providers=15`, `organizations=2`, active queued/running/retry executions `0`; disposable restore container removed after verification.
- Rollback anchors retained before mutation: Backend image `sha256:438bf7817b7740aa5ee97aba256979da834a16669c95639dbec03a5af26b7797` tagged `aionex-aios-backend:rollback-pr410-20260817T1626Z`; Project Worker image `sha256:73e54cb8053e8cdefb5af91edbb966bef99a23a23d6048891921a46e1c4c43fc` tagged `aionex-aios-project-worker:rollback-pr410-20260817T1626Z`.
- Controlled build/deploy: combined Production Compose + Phase36B worker-scale configuration parsed successfully with profile `ai-execution`. Before recreation it resolved `PROJECT_EXECUTION_RUNNER_MODE=legacy`, `PROJECT_AI_LIVE_RUNTIME_ENABLED=false`, `PROJECT_AI_MODEL_REFRESH_ENABLED=false`, `PROJECT_EXECUTION_LEGACY_MODEL=gpt-5.6-luna`, and `PROJECT_EXECUTION_RESEARCH_MODEL=gpt-5.6-luna`. Only Backend and Project Worker images were rebuilt; new image IDs are Backend `sha256:5709f9e52486fbdff79294cc31c80ac66c8fde209f5f6df37a923b804bd789d8` and Worker `sha256:ab2471c53a954283e37fb50c0d05425fb2726824cf094762b8fd4fc3c4cb7515`. Backend was recreated and proven healthy first; both Workers were then recreated with scale `2` and both became healthy. PostgreSQL, Redis, Nginx, Frontend and Portal were not recreated.
- Post-deploy runtime proof from inside Backend and both Workers: runner `legacy`; Phase36C live runtime `False`; automatic model refresh `False`; legacy planning model `gpt-5.6-luna`; research model `gpt-5.6-luna`; fixed project execution budget `0.05 USD`. `ProjectPlanningRunner` constructed successfully in all three containers without provider calls. Production schema stayed `0029`, active ProjectExecutions stayed `0`, and provider rows with persisted `validated_models` stayed `0`; no automatic model evidence write or generation/spend occurred.
- Worker/ingress evidence: durable registry reports exactly `2` online Workers, capacity `2` each, aggregate capacity `4`, aggregate active `0`; replaced worker registrations are marked `stopped`. API `/ready` returned `20/20` HTTP 200 with p50 `204.3ms`, p95 `322.1ms`, max `340.9ms`, within the retained Phase36B lightweight-read `<=500ms` boundary. `vip-e.net` and `ai.vip-e.net/en/` returned HTTP 200. `gabarot.vip-e.net` returned the expected HTTP 302 to the configured Cloudflare Access login, confirming the private-owner boundary remains enforced. Backend and Worker recent logs contain no error/traceback/critical matches.
- PostgreSQL operational note: the long-running PostgreSQL container still has its older runtime healthcheck `pg_isready --host 127.0.0.1 --port 5432 --quiet`, which attempts the nonexistent role `root` and creates repeated harmless FATAL log noise. The merged Production Compose source is already corrected to pass `--username "$POSTGRES_USER" --dbname "$POSTGRES_DB"`. PostgreSQL was intentionally not recreated solely to update this healthcheck because that would introduce an unnecessary database outage; this is source-fixed/runtime-healthcheck-pending until the next planned PostgreSQL recreate. Database health, backup/restore, schema and application queries remain green.
- P36-0015 is now **deployment-closed** for the active Backend/Project Worker rollback path: the live containers no longer carry stale GPT-5 mini/nano project defaults, while Phase36C remains explicitly unarmed. Remaining 36C launch gates are still: Owner-reviewed fresh validated-model persistence, production provider invoker/error mapping, provider credit/quota alert proof, bounded live-provider acceptance, then controlled Phase36C canary/two-Worker live route/fallback/memory acceptance. Do not enable `PROJECT_EXECUTION_RUNNER_MODE=phase36c` or `PROJECT_AI_LIVE_RUNTIME_ENABLED=true` before those gates are green.
- Safe point: Production is healthy on Alembic `0029`, Backend + two Workers are on the PR #410 current-model source, runner remains `legacy`, live runtime/model refresh remain disabled, active executions `0`, rollback images and a verified fresh database backup are retained.
### 36C live-provider / two-worker acceptance closeout — 2026-08-17T16:50:58Z

- Protected deployment-evidence PR #412 merged to `main` as `7a6b31c3479f8dd4cbddf2432c6a41d97e65bc35` with all required checks green. Production remained Alembic `0029`, two healthy `legacy` Project Workers, live runtime disabled, automatic model refresh disabled and active ProjectExecutions `0` throughout the acceptance work.
- Fresh credential-specific model evidence was persisted transactionally from Production inventories at `2026-08-17T16:34:47.894437Z`, TTL `21600s`, with no unavailable models, probe failures or revocations. Current launch evidence is exactly Free `ollama:gemma3:4b`; Paid `mistral:mistral-medium-3-5`, `deepseek:deepseek-v4-pro`, and OpenAI `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`. Evidence expires at `2026-08-17T22:34:47.894437Z`.
- Owner plan policy is now explicit in Production: Free is local Ollama-only, cost cap `$0`, privacy/offline, no fallback; Paid allows the five freshly validated external models, cost cap `$1.00`, max one fallback. No user override was needed for the retained canaries. Provider credentials remain only in the protected platform provider pool.
- Bounded live-provider acceptance used the production `ProjectAILiveProviderInvoker`, exact persisted evidence and an in-memory `32` output-token cap. All `6/6` launch models returned successfully. External acceptance spend was `$0.00041937`; metadata-only evidence is `/opt/AIOS/.deployment-backups/phase36c-live-provider-acceptance/acceptance-20260817.jsonl`, SHA-256 `8b4cfcdbf0b9bcef10647a1f1a0390887f9aa1cff10fa1c259cbae42295d5fb6`. Prompt and response bodies were not retained in the evidence file.
- Full Free Project-AI integration canary ran inside the real Project Worker `NullPool` environment and completed planner/researcher/coder/reviewer `4/4` through `ollama:gemma3:4b`, with four durable route attempts, four project-scoped memories, zero retries/fallbacks and `$0` provider cost. An earlier Backend-container attempt was rejected before provider use because Backend pooling is intentionally not the worker thread/loop shape; all synthetic data from that attempt was removed.
- Full Paid integration canary first proved that an artificially tiny `32`-token reasoning bound is insufficient for the complete planner graph; its synthetic data was removed. The retained bounded `128`-token run completed all four roles with six attempts, two real fallbacks, four project-scoped memories and total calculated cost `$0.011112`. Planner and coder fell back from GPT-5.6 Sol to GPT-5.6 Terra; researcher/reviewer completed on Sol.
- Two-worker acceptance used two isolated paid organizations and resource class `phase36c-canary`, which the running `legacy` workers cannot claim. The first `128`-token trial truthfully completed `1/2` and preserved zero cross-tenant memory; evidence SHA-256 `e0f8513ce272d6017e5e0d00fddd47ab62f505895613c0f7ad25639bace911d9`. A diagnostic `256`-token rerun then completed `2/2` on two distinct canary Workers with four memories per project and `cross_tenant_memory=0`; one route produced sanitized `provider_response` and successfully fell back from Sol to Terra. Retained evidence `/opt/AIOS/.deployment-backups/phase36c-two-worker-acceptance/diagnostic-20260817.json`, SHA-256 `77ab0a5999249229acd26142007113785064ff89ac268717d751557ba34e04c2`. All synthetic organizations/executions were deleted after measurement.
- Owner provider-finance alert delivery was proven end-to-end without fabricating a real balance. A temporary `phase36c-drill` provider used explicitly synthetic `$1.00/$0.75/$0.25` funded/low/critical values only for the drill. Two alert evaluations deduped to one notification, manually labeled `[PHASE36C TEST DRILL]`; in-app was delivered immediately and the configured Owner Telegram channel delivered on attempt `1`. The temporary provider and finance policy were deleted; notification `1b5c8673-e29f-4714-95a5-9750cb8a0200` remains with `synthetic_drill=true` as audit evidence.
- Production-image selector proof remains double-armed: `PROJECT_EXECUTION_RUNNER_MODE=phase36c` with live arm false throws `ProjectExecutionConfigurationError`; the same image with the explicit live arm true builds `DeterministicProjectAIIntegrationRunner` using `ProjectAILiveProviderInvoker` and Redis prefix `aionex:project-ai:live:v1`. The running service processes themselves were not switched.
- Consolidated closeout evidence: `/opt/AIOS/.deployment-backups/phase36c-live-closeout/closeout-20260817.json`, SHA-256 `0a4da3dd8afa6b538fe87e0473610c949cdd1e9431a4f0da8da8b605fc69d9c3`. Real multi-provider routing and tenant/project memory isolation are therefore promoted from `locally_executed` to `runtime_verified`; Batch 36C remains `in_progress` rather than overstating launch finality.
- **Only remaining external Owner input before paid-user production arm:** record the real funded-credit baseline plus low and critical thresholds for each paid provider. Production currently has zero real `project-ai-provider-finance` records. These financial values cannot be inferred from model usage or safely fabricated. Until they are supplied, keep `PROJECT_EXECUTION_RUNNER_MODE=legacy`, `PROJECT_AI_LIVE_RUNTIME_ENABLED=false`, and `PROJECT_AI_MODEL_REFRESH_ENABLED=false`. After real finance records are committed, refresh model evidence again, enable the 4-hour refresh observer with the live arm, verify `active_jobs=0`, then perform the final controlled Worker switch with the retained rollback images/database backup.
### 36C post-closeout real `$0.05` execution-budget correction — 2026-08-17T17:01:46Z

- PR #413 closeout evidence remains valid for real provider invocation, fallbacks, two-worker concurrency and tenant/project memory isolation. It intentionally left Batch 36C `in_progress`. A later production-path check added one missing condition: the public ProjectExecution API always creates non-neutral executions with `PROJECT_EXECUTION_BUDGET_CAP_USD=0.05`, so the complete Paid route plan must be admissible under that exact durable ceiling before user traffic can be armed.
- On current merged `main` before this correction, a synthetic Paid consumer with the real Owner Paid model policy and an exact `$0.05` ProjectExecution failed **before provider execution** with `ProjectAIBudgetExceeded: route plan exceeds durable execution budget`. No provider call or spend occurred in this failing proof. The preceding planner-only diagnostic selected GPT-5.6 Sol primary (`$0.03009` estimated) and GPT-5.6 Terra fallback (`$0.012036`) for the planner task, confirming that credentials/model evidence were not the cause.
- Root cause: `ProjectAIRoutePlanner` ranked each task independently against the broader Owner Paid ceiling (`$1.00`) and picked the top model before the durable store later clamped the completed plan to the execution budget (`$0.05`). The system therefore rejected a plan even though lower-ranked validated models could satisfy the same task graph within the real execution budget. Raising the user budget was rejected as a workaround.
- Isolated source fix `fix/phase36c-budget-aware-routing`: the planner now filters ranked candidates against the **remaining** total budget and selects the highest-ranked affordable route; `DurableProjectAIRouteStore` computes the effective ceiling as `min(ProjectExecution.budget_cap_usd, Owner policy ceiling)` **before** resolver/planner fingerprinting and persists that effective policy. Existing attempt-time integer micro-USD reservation remains the final enforcement layer.
- Current launch-model regression after the fix builds all four roles within the real ceiling: total primary estimate `$0.0479034`; planner `gpt-5.6-sol`, researcher `gpt-5.6-terra`, coder `gpt-5.6-luna`, reviewer `gpt-5.6-luna`, each with an approved affordable fallback where available. This complements rather than replaces PR #413 runtime evidence: #413 proves live execution/fallback/memory behavior, while this correction proves the same launch policy can be admitted by the real `$0.05` API budget boundary.
- Verification before PR protection: routing + launch-model focused `13/13 PASS`; all `test_phase36c_*.py` `61/61 PASS` on disposable PostgreSQL 16 + Redis 7 at Alembic `0029`; focused Ruff PASS; focused Mypy PASS; `git diff --check` and Phase36 reporting invariant PASS. Disposable test services were removed.
- Initial PR #414 Python CodeQL job failed only with GitHub infrastructure `No server is currently available to service your request`; no source/security annotation was reported. `main` advanced through PR #413 during that CI run, producing documentation-only merge conflicts plus the Phase36 registry promotion from #413; the correction branch keeps the #413 closeout first and records this newer budget finding after it.
- Production remains deliberately unchanged by this source correction: both Workers stay `legacy`, `PROJECT_AI_LIVE_RUNTIME_ENABLED=false`, automatic model refresh remains disabled and active ProjectExecutions remain zero. After protected merge/deploy, rerun the exact `$0.05` Paid full-plan/canary before any user arm.
- Real provider-finance values remain an external Owner/account input: production still has zero non-synthetic `project-ai-provider-finance` records. The synthetic alert drill in PR #413 proved delivery/deduplication but did not fabricate real funded balances. Final Paid arm still requires truthful funded-credit plus low/critical thresholds for each paid provider.
### 36C budget-aware routing production deployment + exact `$0.05` runtime proof — 2026-08-17T17:34:24Z

- Budget-aware routing PR #414 merged to `main` as `66bab574aef94544ef0e85d55fe2385d2116224a` after all protected checks were green. The first CodeQL attempts failed only because GitHub returned repeated infrastructure `503 No server is currently available`; rerun attempt #2 completed Python + JavaScript/TypeScript `2/2 SUCCESS`. Production Docker Build and every other protected gate completed successfully before merge.
- Pre-deploy safety gate: active ProjectExecutions `0`. Fresh Production backup `/opt/AIOS/.deployment-backups/phase36c-budget-aware-deploy/aios-20260817T172306Z.tar.gz`, SHA-256 `834d87e9ba4da2c438f14e274209e2ae9daa1fc8a64c68018eee659b9451c7ac`. Disposable PostgreSQL 16 restore smoke matched Alembic `20260817_0029`, `project_executions=1`, `ai_providers=15`, `validated_provider_rows=4`, `plan_policy_records=2`, `real_finance_records=0`, active executions `0`; disposable restore infrastructure was removed.
- Rollback images were retained before mutation: Backend `sha256:5709f9e52486fbdff79294cc31c80ac66c8fde209f5f6df37a923b804bd789d8` tagged `aionex-aios-backend:rollback-budgetfix-20260817T1724Z`; Project Worker `sha256:ab2471c53a954283e37fb50c0d05425fb2726824cf094762b8fd4fc3c4cb7515` tagged `aionex-aios-project-worker:rollback-budgetfix-20260817T1724Z`. New built tags are Backend `sha256:8d873d2c706d864f43d89c97ccc2178bb9778caccfd3f83bd780d6b5d04c32aa` and Worker `sha256:ac81ed041573ffe40fc7c0a6f7a7189ae400b0d252f17bc1c47764b03d5c43c1`.
- Controlled deploy recreated only Backend and the two Project Workers. Backend was recreated/proven healthy first; then `project-worker=2` was recreated and both Workers became healthy. PostgreSQL, Redis, Nginx, Frontend and Portal were not recreated. Post-deploy source proof inside all three updated containers contains the budget-aware `remaining_budget` planner path plus durable `effective_policy` clamp. Runtime flags remain `PROJECT_EXECUTION_RUNNER_MODE=legacy`, `PROJECT_AI_LIVE_RUNTIME_ENABLED=false`, `PROJECT_AI_MODEL_REFRESH_ENABLED=false`, budget `$0.05`, legacy/research `gpt-5.6-luna`.
- Post-deploy durable state stayed intact: Alembic `0029`, validated provider rows `4`, Owner plan policy records `2`, real provider-finance records `0`; exactly two current Workers are online, aggregate capacity `4`, aggregate active `0`, active ProjectExecutions `0`.
- Output-bound diagnostics were retained as diagnostics only, not launch evidence. At artificial `256` tokens the exact-budget full canary reached planner/researcher but coder returned sanitized `provider_response` on Luna and DeepSeek while budget remained healthy (`$0.006252` spent of `$0.05`, primary estimate about `$0.047963`). A direct Luna coder diagnostic succeeded at `512` tokens for `$0.0006188`; however another full `512`-token run showed variable reasoning-output exhaustion at planner. These findings prove that synthetic output caps distort GPT-5.6 reasoning behavior and must not substitute for real-runtime acceptance. Diagnostic evidence SHA-256 values include `e7a998fcc6d7f9f5b052edfd934f6b0bca75b96f24f0b7e584473a9ff2799d25` (256 full diagnostic) and `c00ac909c27a9ce61229fa5350e16408440fc8c735ccc174ca20118a566bc3bf` (coder 512 bound).
- **Retained exact production-runtime acceptance PASS:** one isolated Paid organization/project executed the complete four-role Phase36C runner with the provider runtime completely unmodified (provider default output bound, no monkeypatch), exact ProjectExecution budget `$0.05`, and the post-#414 budget-aware source. The durable plan used effective policy `$0.05`, primary estimate `$0.048022`; planner `gpt-5.6-sol`, researcher `gpt-5.6-terra`, coder/reviewer `gpt-5.6-luna` all completed as primaries, `4/4` route attempts succeeded, retries/fallbacks `0`, project-scoped memories `4`. Actual calculated provider cost was `$0.0446096`; durable spent amount `$0.044609`, reserved `$0`, therefore execution remained below the real five-cent ceiling. Evidence `/opt/AIOS/.deployment-backups/phase36c-budget-aware-deploy/paid-exact-budget-real-runtime-20260817.json`, SHA-256 `bf571ecaae1d30bb72b1157e24a3138d0737e1fb12050751915664cf675b0d98`. Prompt/response bodies are not stored in the evidence; only route/cost/latency/result hashes are retained. Synthetic organization/execution cleanup returned zero rows.
- This exact `$0.05` proof closes the post-PR413 budget-admission blocker. It complements the retained PR #413 two-worker evidence (two distinct canary Workers, `2/2` projects, four memories each, `cross_tenant_memory=0`) because #414 changes route affordability/admission only, not worker claim/concurrency or memory isolation. Both updated production Workers contain the same merged budget-aware source and remain online with aggregate capacity `4`.
- Post-canary safety: active executions `0`, canary organizations/executions `0`, Backend/Workers healthy, no recent traceback/critical/panic/fatal matches. Docker's real Backend health endpoint `/ready` returned `20/20` HTTP 200 locally with p50 `3.11ms`, p95 `5.51ms`, max `12.34ms`. The public website and user portal returned HTTP 200; Owner host returned the expected Cloudflare Access HTTP 302. Public `/api/ready` is not an exposed route and correctly returns frontend 404, so it is not used as the Backend readiness metric.
- **Remaining non-fabricatable gate:** Production still has zero real `project-ai-provider-finance` records. Real funded-credit baseline and low/critical thresholds for each Paid provider are Owner/provider-account facts and cannot be inferred safely from usage or synthetic drills. Therefore the correct safe state remains `legacy` + live runtime disabled + automatic model refresh disabled. Before final Paid-user arm: record truthful provider-finance values, refresh credential-specific model evidence again, verify active jobs `0`, then perform the explicitly armed Worker switch with retained rollback images/database backup.
- Safe point: all source, deployment, exact-budget routing/runtime, fallback/concurrency (PR #413), tenant memory and rollback evidence that can be completed without inventing Owner financial data are green and retained. Batch 36C remains `in_progress` solely behind the explicit real-finance/Owner activation boundary rather than overstating production launch finality.

### 36C final technical closure / transition to 36D — 2026-08-17T18:15:00Z

- Batch 36C is now **complete for its owned technical scope**. The retained evidence chain covers durable multi-provider routing, provider-specific validated-model evidence, budget-aware `$0.05` admission/accounting, live provider invocation, fallback, two-worker execution, tenant/project-scoped memory isolation, rollback/backup/restore, Owner policy controls, and Launch-100 deterministic isolation/admission. The exact production-runtime Paid canary remained below the real `$0.05` execution ceiling and Production returned to zero active jobs with healthy Backend/Workers.
- Program semantics remain truthful: completing 36C does **not** fabricate or silently satisfy external activation facts. The registry retains these explicit gates on their capabilities: `owner-provider-funded-credit-thresholds`, `store-signing-and-publication`, `platform-code-signing`, `live-payment-provider-credential`, and `physical-device-or-chain-deployment-authority`. These are external Owner/provider/platform/deployment facts, not missing internal 36C source work.
- Paid Project-AI user arming remains fail-closed while Production has zero real `project-ai-provider-finance` records. The running services intentionally remain `PROJECT_EXECUTION_RUNNER_MODE=legacy`, `PROJECT_AI_LIVE_RUNTIME_ENABLED=false`, and `PROJECT_AI_MODEL_REFRESH_ENABLED=false` until truthful finance values are recorded and the explicit arm procedure is performed. Closing the batch records technical completion; it does not bypass the external activation gate.
- Current software-family maturities remain evidence-based rather than inflated: multi-provider routing and tenant memory are `runtime_verified`; the universal software/application families historically proven through Phase 28/29 remain `locally_executed` where no broader production activation evidence exists. External signing/payment/device gates remain attached to the corresponding capability.
- Registry transition: `36C=complete`; `36D=in_progress`; authoritative `current_batch=36D`. This transition starts no 36D media mutation by itself. The next work must begin from merged 36C closure evidence and build the Universal Creative Asset Graph / Media Orchestrator without reopening closed 36C work unless a regression is proven.
- Safe boundary: Production remains healthy on Alembic `0029`, two Project Workers are healthy with aggregate capacity `4`, active ProjectExecutions are `0`, validated launch-model evidence and Owner plan policies remain retained, and all non-fabricatable external gates remain explicitly visible instead of being reported as complete.
### 36C protected merge + Production registry activation evidence — 2026-08-17T18:45Z

- Protected PR #417 `Phase 36C final technical closure` merged to `main` as `a334ddb2ffb6478c4919d5843afce4ba7f974697` after all required checks were green. The first JavaScript/TypeScript CodeQL attempt failed only because GitHub returned infrastructure `503 No server is currently available`; the failed CodeQL job alone was rerun on the same head and completed successfully. Python CodeQL, Backend Tests, Production Docker Build, Browser boundaries, SBOM/vulnerability, repository secret hygiene, Core Owner/Release/Web contracts, Frontend Build, Dependency Security and Phase36 Reporting all passed.
- Pre-activation Production gate: active queued/running/retry ProjectExecutions were `0`. `/opt/AIOS` was fast-forwarded from `d3b89b6` to the merged `main` closure `a334ddb`; no database migration, image rebuild, provider call or worker restart was required for the registry-only transition.
- Only the Backend container was restarted so its in-process `aios.phase36_program` module would reload the merged registry from `/workspace/src`. Backend returned healthy after restart and `/ready` passed `10/10`; active ProjectExecutions remained `0`.
- Production snapshot after reload: `36A=complete`, `36B=complete`, `36C=complete`, `36D=in_progress`, authoritative `current_batch=36D`. The public non-secret API `/api/v1/capabilities/phase36` returned HTTP `200` with `current_batch=36D`, so Owner/User completion surfaces now consume the advanced state.
- Safety flags were unchanged in Backend and both Project Workers: `PROJECT_EXECUTION_RUNNER_MODE=legacy`, `PROJECT_AI_LIVE_RUNTIME_ENABLED=false`, `PROJECT_AI_MODEL_REFRESH_ENABLED=false`, execution budget `$0.05`. Both Workers remain healthy and were not restarted for this transition.
- External activation gates remain explicitly retained rather than fabricated: provider funded-credit thresholds, mobile store signing/publication, desktop code signing, live payment-provider credential, and physical-device/chain deployment authority. These gates do not reopen closed 36C internal implementation; they remain capability-specific external activation facts for the later final release ledger.
- **Batch 36C is closed.** No 36D implementation was started by this activation. The next engineering batch is 36D — Universal Creative Asset Graph and Media Orchestrator.

### 36D foundation checkpoint 1 — latest-stack DAG/storage schema — 2026-08-17

- Started strictly from merged Phase36C closeout (`main@7e418f6`) with Production healthy and `current_batch=36D`; no Production mutation was made.
- Latest-stable review raised the media engine target from historical FFmpeg `8.1+` to **FFmpeg 9.0**; retained current `sharp 0.35.3`; prepared `boto3` upgrade `1.43.67 -> 1.43.72`; storage remains S3-compatible/provider-neutral with local private-volume mode plus AWS S3/R2-compatible endpoints.
- Reused existing Phase29H `StudioJob`/`StudioAsset`/`StudioAssetRevision` and Studio worker rather than creating a second user-facing asset system. New 36D layer adds deterministic creative DAG nodes/edges, rights/provenance/scene/timeline metadata, downstream-only revision planning, output profiles, render-step persistence and local/S3-compatible object storage.
- Alembic `20260817_0030` adds `media_asset_graphs`, `media_asset_nodes`, `media_asset_edges`, and `media_render_steps`. Disposable PostgreSQL 16 proved `0029 -> 0030 -> 0029 -> 0030`; focused media tests `5/5 PASS`, Ruff PASS, Mypy PASS, requirements dry-run PASS, `git diff --check` PASS.
- Maturity remains truthful: all three 36D capabilities stay `specified` and Batch 36D stays `in_progress` until a real FFmpeg 9.0 render worker, resumable step execution, object-storage evidence and the complete scene-revision/final-assembly exit gate are proven.
- Safe point: foundation is source-only; Production stays Alembic `0029` with no new media tables or media runtime enabled.

### 36D PR #419 CI correction — 2026-08-17T19:23:00Z

- Initial protected CI exposed two source-contract regressions only: the repository zero-dead/market-readiness audit rejected a `bare pass` around local media-root permission hardening, and the Backend Alembic-head contract still expected `20260817_0029` after migration `0030` was introduced. No provider, storage, database or Production runtime failure was involved.
- The local object-store constructor now fails closed with sanitized `MediaStorageError` if private-root permissions cannot be hardened instead of silently continuing. The Backend head contract now truthfully expects `20260817_0030`. Focused root zero-dead/market-readiness is `5/5 PASS`; Backend Alembic-head + Phase36D foundation is `6/6 PASS`; Ruff PASS. Production remains untouched on Alembic `0029` pending protected merge/deployment.

### 36D execution checkpoint 2 — FFmpeg 9 durable render fabric — 2026-08-17T20:25Z

- Foundation PR #419 is merged as `0d66895e2061fd3bf0d747c3abd6f877912bbd14`. Execution layer now adds migration 0031 fencing/recovery, dependency-aware Media Render Worker, real FFmpeg 9 image, profile QA, S3/local storage inheritance, Studio media-graph API bridge and StudioAssetRevision materialization.
- Real shipped-image acceptance rendered/probed H.264/AAC MP4 assembly, AV1/Opus WebM, PNG and PCM WAV; evidence SHA-256 `f091ec6faa7df145193dcf6614d1f9c5173bb97745efe2321e2f698daffe0f18`. Partial revision tests prove an unchanged scene is reused while the changed scene and downstream assembly alone are regenerated; stale worker completion is fenced.
- Local/pre-merge gates: 36D + legacy Studio `20/20` PASS; broader Backend regression `21/21` PASS; zero-dead/market-readiness `5/5` PASS; Ruff/Mypy/Compose/YAML PASS; migration 0031 downgrade/re-upgrade PASS.
- Production is intentionally still Alembic 0029 with no Media Worker activated. Remaining gates are protected CI -> fresh backup/restore -> 0030/0031 migration -> one healthy Media Worker with real inherited S3 preflight -> isolated Production render/revision/assembly exit gate -> cleanup/post-health -> 36D closure.

### 36D executable render/runtime checkpoint 2 — FFmpeg 9 + resumable DAG — 2026-08-17T20:25Z

- Foundation PR #419 merged to `main` as `0d66895e2061fd3bf0d747c3abd6f877912bbd14` after all protected checks passed. This checkpoint builds on that merged DAG/storage schema rather than rewriting the Phase29H Studio asset system.
- Latest engine is now reproducibly built as a dedicated `media-worker` Docker target from the official FFmpeg `9.0` source tarball. Build verifies SHA-256 `7f607a00dd0d28a729d5a4811205812eef01cf6ef6155025febb6f36a9062d52`, imports the official FFmpeg release key, verifies fingerprint `FCF986EA15E6E293A5644F10B4322F04D67658D8`, and verifies the detached release signature before compilation. The image includes governed software codecs plus compile-time VAAPI/oneVPL-QSV adapters; hardware use remains fail-closed unless explicitly operator-armed.
- Alembic `20260817_0031` extends render steps with `lease_owner`, `lease_expires_at`, `fencing_token`, and `available_at`. Disposable PostgreSQL proved `0031 -> 0030 -> 0031`; stale workers cannot renew or complete after a lease is reclaimed and fencing generation advances.
- Added durable `MediaRenderWorker`: dependency-aware claim ordering, lease renewal during long render/upload, retry/backoff, exhausted-lease failure, checksum-verified inputs, deterministic fencing-specific output keys, FFprobe QA, storage upload, immutable provenance and stale-completion rejection. Assembly is not claimable until all parent nodes are completed.
- Media storage now defaults to `inherit`, so the Phase36D worker reuses the existing governed `STORAGE_TYPE` boundary when configured (including the current S3 setup) while retaining explicit local mode for development/acceptance. Both Local and S3-compatible backends expose a fail-closed preflight.
- Studio integration now exposes tenant-scoped media graph create/list/get, completed-graph partial revision, and final output endpoints. Public graph snapshots omit prompt metadata and physical storage keys. Revisions are rejected until the source graph is completed; non-software hardware selection is rejected at the user API unless a later operator policy explicitly enables it.
- Universal Builder integration converts its real `editable-storyboard` target into an executable Media DAG. Contract tests use the actual `_media_target()` storyboard schema rather than a duplicate fixture.
- **Real local exit-gate acceptance with FFmpeg 9.0 PASS:** V1 rendered two H.264/AAC scenes and final assembly in exactly `3` durable steps. V2 changed only `scene-b`; dependency impact was exactly `scene-b + final`, so V2 executed only `2` render steps, reused `scene-a` with unchanged checksum `434af8e834ec3877edb9db13a2ab149f99c651f1e66737869bc9792d0d303c57`, and produced a different final checksum (`c5b3a2e68fb85eeac01c75e1d28bc6a86a3651f4a730def45cd06971645ba97d` -> `873b9366e79097ab5b7d8f7b4757905c76a00704f51ae2c6f2a0829a021dd389`). Final sizes were `23698` and `23682` bytes; provenance remained attached.
- Final media-worker image built from the latest source as `sha256:07f1e5797e3fef1f4c749be7c3a8f95654cfad94b53f39645328eefd6259c590`. Image-level smoke rendered/QA-probed real H.264/AAC video (`22114` bytes), PNG (`1506` bytes), and PCM WAV (`96078` bytes); smoke JSON SHA-256 `89dc4f87ab36151bf575874f0a8f9624596274fa334b6b8427d0fb422b38caeb`. Runtime preflight reported FFmpeg `9.0` and adapters `software,vaapi,qsv,drm`.
- Current source verification: Phase36D DAG/worker/Alembic focused `12/12 PASS`; Studio media API `1/1 PASS`; retained Phase29H Studio regression `4/4 PASS`; root zero-dead/market-readiness `5/5 PASS`; Ruff PASS; Mypy PASS. CI now builds and runs a real FFmpeg media-worker smoke instead of validating Backend images alone.
- Production remains intentionally untouched by checkpoint 2: schema stays `0029`, no media-worker service is running, and no Production media object was created. The next protected transition is source PR/CI -> merged source -> fresh Production backup/restore -> controlled `0029 -> 0031` migration -> real inherited-S3 preflight/put-get-delete -> start media-worker -> isolated Production V1/V2 exit-gate canary -> cleanup/evidence -> only then close 36D and advance registry to 36E.


### P36-0016 — Media Worker non-root activation correction — 2026-08-17T21:05Z

- First Production Media Worker activation exposed a least-privilege startup conflict: `cap_drop: ALL` prevented the generic root entrypoint from chowning unrelated runtime roots. The media volume/temp paths themselves were already private and UID 1000 writable; real S3 preflight passed from a Compose-equivalent UID 1000 one-shot.
- Corrective candidate runs only Media Worker as `1000:1000`, retains `cap_drop: ALL` + `no-new-privileges`, adds a two-Compose regression contract, and leaves the Production worker stopped until protected merge. Migration 0031 and Backend remain healthy; active Project/Studio/Media queues remain zero.
