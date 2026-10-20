# Phase 36I — verified LOD delivery integration

Date: 2026-10-20 UTC  
Scope: FR16 delivery of precomputed, checksum-bound GLB variants.  
Status: implementation and focused local checks passed; protected CI and product runtime acceptance are separate gates.

## Problem

PR #947 provides registered model selection for desktop, mobile and low_power.
The delivery service still admitted only one GLB per logical asset, so it could
not populate the three-profile registry from actual staging artifacts. Its
browser QA also assumed that low_power always loaded zero model resources.

PR #947 was reviewed and merged normally at
892633095b54a31156cdf0d14bcc7aa4dddf75c0, with 11 required jobs successful and no
unresolved review threads on head c040c8d255ca6232637d0daf6d27bbf8ceecbb7c.
This change is based on that merged contract.

## Changes

- Admit an optional lod_variants array containing exactly one mobile and one
  low_power GLB. The original asset supplies desktop. Existing manifests without
  LOD variants retain their current behavior.
- Require safe relative GLB paths, explicit SHA-256, bounded positive integer
  sizes and complete, unique profiles. Read files through directory handles
  without following symlinks; reject special files and hardlinks, verify file
  identity and content, and repeat verification when copying.
- Reject non-GLB variant containers and external buffer/image resource URLs.
  This is bounded admission, not a complete glTF conformance validator.
- Populate the existing SceneAsset.lod_profile registry without adding a
  competing contract. Each logical model still creates one zone reference;
  variants do not become additional zones.
- Copy every registered variant and retain its digest, bytes and inspected
  metadata in the delivery manifest.
- Compute transfer bytes and expected model paths for each profile from the
  actual selected registry. The total model payload still accounts for every
  packaged file.
- Make browser QA compare observed model URLs with the exact selected local
  resources for every profile. Explicit low_power variants are now expected;
  legacy lazy models still expect no low_power model fetch.
- Add the existing backend httpx==0.28.1 pin to core development dependencies so
  the integration tests import the real delivery service in a clean core CI job.

## Verification

The focused command below passed **68 tests**, with zero failures or skips, on
the isolated worktree. The last run completed in 2.18 seconds with Python 3.11.2.

    LC_ALL=C.UTF-8 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 \
      /opt/AIOS/.venv/bin/python -m pytest -q --tb=short --maxfail=3 \
      tests/test_fr16_lod_delivery.py \
      tests/test_phase30a_3d_web_contracts.py \
      tests/test_phase30b_3d_asset_pipeline.py \
      tests/test_phase30f_3d_project_lifecycle.py \
      tests/test_phase36_autonomous_3d_full_project.py

New tests cover malformed evidence, incomplete and duplicate groups, traversal,
symlinks, hardlinks and special files, tampering after admission, external model
resources, registry/zone mapping, copied hashes, complete manifests, profile byte
accounting, legacy behavior and exact browser model-resource matching.

Packaging unit tests stub npm and browser execution explicitly and assert that
release_ready remains false. They do not claim build or browser acceptance.

A separate measurement used the actual previously accepted isolated Blender
fixture. It verified the original fixture receipt digest, matched every input
GLB digest to that receipt, exercised the real admission/copy functions,
materialized and validated the scaffold, inspected the copied models and ran the
lifecycle asset budgets. All three file entries were retained in its manifest.

| Profile | GLB bytes | Triangles | Materials | Animations | Images |
| --- | ---: | ---: | ---: | ---: | ---: |
| desktop | 285816 | 3970 | 2 | 1 | 1 |
| mobile | 185948 | 1786 | 2 | 1 | 1 |
| low_power | 92744 | 872 | 2 | 1 | 1 |

Measurement:

    /var/lib/aionex-migration/launch-continuation-20261020T1340Z/fr16-lod-delivery/VERIFIED-LOD-DELIVERY-FIXTURE-ATTEMPT2.json

SHA-256:

    3d0df1dc5014ed223cc3d0e1765ab06248d040422bd69af0386174b16d08de1b

Pinned original fixture receipt SHA-256:

    655c63a6ad90a5982b89a829376b142826323f7f727889fb2e4f506a7f6d2218

## Independent review follow-up

The review of the first proposed head found two integration boundaries. Both
are addressed before merge:

- Admission now enforces the existing eight-zone model limit. Eight logical
  models remain supported with or without LOD variants; a ninth is rejected
  before package construction instead of being silently left unreferenced.
- Lifecycle budgets now select the matching explicit LOD member for every
  profile, while preserving legacy complete-package and lazy-proxy behavior.
  The artifact manifest still includes all files. Tests use three groups with
  11 MiB desktop, 5 MiB mobile and 1 MiB low_power models to prove that mobile
  is not charged for desktop files or the complete 51 MiB package. A negative
  case with 11 MiB mobile files still fails its 10 MiB per-file budget.

The fixture measurement was repeated against these reviewed source files; the
current proof above includes the lifecycle file hash as well as the delivery,
test and development-dependency hashes. The earlier measurement remains intact
as historical evidence.

## Acceptance boundary

The measurement proves delivery integration for the existing generated fixture.
The delivery service did not execute Blender, generate new optimized models or
compress assets. The record explicitly says that compilation and browser runs
were not performed in this measurement and that release_ready is false.

Protected CI on the exact proposed commit, a complete generated-product build,
browser/WebGL acceptance, representative assets, general optimization and
compression, and physical-device performance remain distinct evidence gates.

No production runtime, existing worker, provider configuration or NS12 observer
was changed. This source change does not close full FR16, authenticated
current-generation recovery, durable worker recovery, the 72-hour observation,
5000-user acceptance, or final release.
