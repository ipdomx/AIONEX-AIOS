# Phase 36I — Part 1 interactive production foundation

Date: 2026-08-25
Status: source foundation + bounded local preflight PASS; 36I remains in progress.

## Scope completed

- Reused the completed Phase 30/34 3D asset, LOD, performance, browser-QA, product, storage and production-generation foundations instead of creating a second 3D stack.
- Added one deterministic Phase 36I planner covering six production families: 2D animation, 2D games, 3D scenes, WebXR AR, WebXR VR and VFX compositing.
- Added explicit requirements for Blender, Three.js, secure context, physical XR-device acceptance, video compositing, LOD and compression per family.
- Added a bounded local Blender preflight with no shell, no network and a minimal environment. The server currently has Blender `4.0.2`; it is deliberately **not production-approved** against the selected `5.2.0 LTS` baseline.
- Added the `https://ai.vip-e.net` application-tunnel delivery boundary. The existing Cloudflare tunnel is valid evidence for HTTPS application/WebGL/WebXR secure-context delivery, but is explicitly **not** treated as proof of direct UDP/TURN/WebRTC reachability.
- Existing portal Three.js is `0.180.0`; the latest closed stable release observed in the technology review is `r185` / npm `0.185.0`. The planner records a controlled migration requirement rather than silently changing the portal dependency in this batch.

## Technology review

- Blender official releases: `5.2 LTS`, released 2026-07-14 and supported until July 2028. Sources: https://www.blender.org/releases/ and https://www.blender.org/releases/5-2/ .
- Three.js official GitHub releases/milestones: `r185` is the latest closed stable release observed; `r186` remained an open milestone during review. Sources: https://github.com/mrdoob/three.js/releases and https://github.com/mrdoob/three.js/milestones .

## Verification

- New Phase 36I foundation tests: `6/6 PASS`.
- Affected Phase 30/36 3D regression: `39/39 PASS`.
- Ruff focused: PASS.
- Mypy focused with imported legacy modules skipped: PASS. A first direct Mypy invocation traversed unrelated pre-existing root modules and reported existing typing debt; no new 36I error was present, so the retained focused invocation isolates this module.
- Python compile and `git diff --check`: PASS.
- First protected Backend CI run stopped after `475` passes on one stale public-capability assertion that still expected `36H`; the public snapshot correctly returned `36I`. The assertion was updated to `36H=external_gate` / `36I=in_progress` and added to the closing gate before CI rerun. No Production change occurred.
- Host Blender probe: `4.0.2`, `production_approved=false`, `network_used=false`.

## Not completed / not claimed

- Blender 5.2 LTS runtime has not been installed or executed.
- Three.js has not yet been upgraded from `0.180.0` to `0.185.0`.
- No new 2D animation/game artifact has been rendered in this batch.
- No WebXR session has been run on a physical AR/VR device.
- No VFX composite has been rendered in this batch.
- No production service, database, provider, GPU job, firewall, DNS, tunnel or public port was changed.
- The preserved Phase 36H public LiveKit/TURN/Egress gate remains external and is not implied by the application tunnel.

## Next short gate

36I.2: build and execute deterministic 2D animation + 2D game templates locally, produce browser/preview evidence, and integrate their artifacts with the existing governed manifest/Studio boundary without provider spend.
