# Phase 30 — 3D Web Creation Capability Program

Purpose: extend AIONEX AIOS so it can autonomously plan, build, validate, optimize and release production-grade Three.js / React Three Fiber projects comparable to and stronger than the IPDomX interaction model, without coupling to IPDomX assets or design.

## Batch 30A — 3D project contract and scene architecture
- Register `3d_web_project` as a first-class project type.
- Define scene/world/zone/player/camera/interaction/audio/performance contracts.
- Define deterministic project blueprint generation and acceptance criteria.
- Define asset registry records for GLB/GLTF, textures, animations, audio and shaders.

## Batch 30B — Asset pipeline and optimization
- GLB/GLTF inspection and metadata extraction.
- Budget gates for bytes, meshes, materials, textures, animations and triangles when metadata is available.
- Compression/optimization planning for Draco, Meshopt and KTX2/Basis.
- LOD and mobile/desktop quality profiles.
- Safe artifact manifests and checksums.

## Batch 30C — Scene builder and runtime scaffolding
- Generate Three.js / React Three Fiber application structure.
- World manager, zones, player/vehicle controller and camera controller.
- Manual + assisted navigation, raycast interactions and responsive controls.
- HTML overlay/content layer and state synchronization contracts.

## Batch 30D — Visual QA and browser acceptance
- Browser-run acceptance contract for desktop and mobile viewports.
- Console/WebGL error collection.
- Route/interaction/camera/asset smoke scenarios.
- Screenshot/evidence manifest contract with explicit unsupported-browser states.

## Batch 30E — 3D performance and release gate
- FPS/frame-time, draw-call, asset-byte and bundle budgets.
- Performance profiles for desktop, mobile and low-power devices.
- Fail-closed release gate when required metrics exceed policy.
- Production build/deploy/rollback evidence integration.

## Batch 30F — Autonomous 3D project lifecycle
- Integrate blueprint → build → asset validation → visual QA → performance QA → approval → release.
- Owner-visible evidence and remediation recommendations.
- Final end-to-end deterministic acceptance proving AIOS can build and govern a complete 3D web project.

No batch may claim external 3D asset generation unless a real configured tool/provider produced the asset. Missing Blender/media integrations remain explicit activation boundaries.

### Batch 30B completion evidence
Status: **complete and verified**.

Implementation: `src/aios/three_d_web/assets.py`.

The retained asset pipeline performs traversal-safe GLB/GLTF inspection, extracts deterministic counts and triangle estimates where the source metadata permits it, detects declared Draco/Meshopt/KTX2/Basis extensions, applies profile-specific byte/mesh/material/texture/animation/triangle gates, creates truthful optimization plans rather than pretending external optimizers ran, defines desktop/mobile/low-power LOD targets, and emits deterministic checksum-addressed manifests with tamper verification.

Automated evidence: `tests/test_phase30b_3d_asset_pipeline.py`.

### Batch 30C completion evidence
Status: **complete and verified**.

Implementation: `src/aios/three_d_web/scaffold.py`.

AIOS now deterministically generates a production-oriented React Three Fiber/Vite source scaffold from a validated 3D blueprint. The scaffold includes a world manager, zone/asset components, player controller, smooth follow camera, manual keyboard controls, assisted zone travel, pointer/wheel/mobile control surfaces, Zustand state synchronization and an accessible HTML overlay layer. Output materialization is traversal-safe and never downloads packages or claims external asset generation.

Automated evidence: `tests/test_phase30c_3d_runtime_scaffold.py`.

### Batch 30D completion evidence
Status: **complete and verified**.

Implementation: `src/aios/three_d_web/visual_qa.py`.

AIOS now has a deterministic visual-QA/browser-acceptance contract for 3D web projects. It defines supported/unsupported/unavailable browser states, desktop and mobile viewport contracts, route/asset/interaction/camera smoke scenarios, console and WebGL error capture records, screenshot/evidence receipts with traversal-safe checksum-addressed paths, deterministic evidence manifests, and a fail-closed visual QA gate that refuses success when required desktop/mobile coverage, screenshots, scenarios, or runtime/WebGL health are missing.

The contract remains truthful: it does not pretend a browser run happened unless a real browser worker supplies a `BrowserRunReceipt`; unsupported browser states require an explicit reason.

Automated evidence: `tests/test_phase30d_visual_qa.py` plus retained 30A–30C tests.

### Batch 30E completion evidence
Status: **complete and verified**.

Implementation: `src/aios/three_d_web/performance.py`.

AIOS now enforces profile-specific 3D performance budgets for FPS, frame time, draw calls, triangles, total scene asset bytes, application bundle bytes and GPU memory where policy requires it. Performance receipts are deterministic and checksum-addressed. The release gate is fail-closed and requires desktop, mobile and low-power results, successful visual QA, successful asset governance, successful production build, valid release evidence, deployment receipt and rollback receipt before release approval.

Automated evidence: `tests/test_phase30e_3d_performance_release_gate.py`.

### Batch 30F completion evidence
Status: **complete and verified**.

Implementation: `src/aios/three_d_web/lifecycle.py`.

AIOS now has a governed autonomous 3D project lifecycle that integrates validated blueprint creation, deterministic runtime scaffold generation, registered asset inspection and manifests, browser/visual QA evidence, profile-specific performance QA, explicit owner approval, and fail-closed production release evaluation with deployment and rollback receipts. The lifecycle emits owner-visible stage evidence, deterministic aggregate SHA-256 receipts, and remediation recommendations for every failed stage. It does not claim browser execution, deployment, rollback, or external 3D asset generation unless corresponding real receipts or configured providers exist.

Automated evidence: `tests/test_phase30f_3d_project_lifecycle.py` plus retained 30A–30E tests.

Phase 30 status: **complete**. Batches 30A through 30F are implemented, tested and merged into the 3D web creation capability program.
