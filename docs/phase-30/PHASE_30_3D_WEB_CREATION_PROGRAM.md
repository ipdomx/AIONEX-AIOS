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
