# Phase 36I — Blender 5.2 LTS 3D expansion receipt

Status: **local runtime acceptance PASS; production unchanged**.

## Implemented source

- Added a bounded local `Blender52CandidateRunner` for the 36I 3D material/animation/environment expansion.
- The runner accepts only a Blender `5.2.x` executable satisfying the `5.2.0` production baseline, runs with `--background`, `--factory-startup`, `--disable-autoexec`, and `--offline-mode`, and writes only below an explicit workspace root.
- The generated scene contains a generated embedded texture, Principled-BSDF PBR hero material, a second environment material, a real keyframed animation, environment ground, key/fill lighting, world background, a GLB export, and a deterministic preview render.
- Runtime receipts remain explicit that no provider, external network, production mutation, or provider GPU job was used.
- Corrected the earlier Blender version parser to accept the official `Blender 5.2.0 LTS` version string.
- Corrected the Blender 5.2 render engine enum from the obsolete `BLENDER_EEVEE_NEXT` spelling to `BLENDER_EEVEE` after isolated runtime execution exposed the mismatch.

## Official renderer artifact

- Artifact: `blender-5.2.0-linux-x64.tar.xz`
- Bytes: `384441228`
- SHA-256: `96f6c181a30f4950607839dc84d42a354b250d8a0231b098b59b7bc69c351c48`
- Runtime location is outside tracked source under `/opt/AIOS/.runtime/phase36i/blender-5.2.0/`; the host `/usr/bin/blender` remains `4.0.2` and was not replaced.

## Real local acceptance

Authoritative successful evidence directory:

`/opt/AIOS/.deployment-backups/phase36i-part3/20260824T214653Z`

Blender 5.2 produced:

- GLB: `4700` bytes, SHA-256 `f99e69e4b1a382eb96f4c87746ecc7a4086d501cfa4902e310839bdad3927d43`.
- Blender preview PNG: `196740` bytes, SHA-256 `c862c45b0f36884fcdef43f1506a4fead8e4458174a3ca16365f6a1c6eb627ff`.
- AIONEX `AssetInspector` measured `2` meshes, `2` materials, `1` embedded texture, `1` animation, `1` scene and `14` triangles.
- Chromium/Three.js r180 then loaded the exact GLB with WebGL and observed `2` meshes, `2` materials, `1` mapped texture, `1` animation, the environment ground and no console error or external request. Browser screenshot SHA-256: `9105c7d838fb9c15961b38a1e71960b55759ee9c0a470b4de5c4ebb3b8e79550`.
- No external provider request, provider GPU job, or production mutation occurred.

## Problems observed and corrected

1. A static-quality command initially referenced a removed temporary venv path. No source or production state was changed; validation was rerun with the existing pinned test venv.
2. Attempt `20260824T214549Z` stopped at preflight because the prior parser rejected the official `LTS` suffix. Parser regression coverage was added.
3. Attempt `20260824T214620Z` entered Blender 5.2 but stopped before artifact export because `BLENDER_EEVEE_NEXT` is not a valid engine enum in this release. The candidate now uses `BLENDER_EEVEE`.
4. The first browser check loaded and rendered the GLB but incorrectly classified an internal `blob:` URL as external and also observed a favicon 404. The evidence harness was corrected to allow internal browser blob/data URLs and supply an empty data favicon; the clean rerun passed.

## Boundaries not crossed

- No production service restart/recreate or schema change.
- No provider request, provider credential change, or spend.
- No host Blender replacement.
- No Three.js package upgrade; portal remains on `0.180.0` pending the protected 36I migration gate.
- No XR device claim and no VFX runtime claim.
- Existing Phase 34 production-verified 3D path remains the production route; this candidate does not replace it yet.
