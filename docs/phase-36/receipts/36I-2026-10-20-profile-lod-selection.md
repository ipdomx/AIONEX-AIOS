# Phase 36I — registered LOD selection by runtime profile

Date: 2026-10-20 UTC
Scope: FR16 generated-client source selection and low-power artifact accounting.
Status: source implemented and focused tests passed; full release acceptance remains open.

## Problem and change

Generated zones previously rendered every referenced registered model without
resolving a LOD group for the current performance profile. Lazy low-power models
always used the legacy procedural proxy.

SceneAsset now accepts an optional lod_profile after the existing checksum
field, preserving positional constructor compatibility. A tagged LOD group must
contain exactly one GLB/GLTF model for each of desktop, mobile, and low_power.
Incomplete, duplicate, or mixed tagged and untagged groups are rejected.

The generated src/runtime/assets.ts selector resolves references to any group
member to one registered variant for the active profile, deduplicates group
references, and preserves registry order and untagged legacy behavior. Zone uses
the selector. AssetModel loads explicit low_power variants even when lazy, while
legacy lazy assets retain the procedural proxy.

Lifecycle accounting includes explicit low-power model files in the low-power
budget. Desktop/mobile accounting remains conservative across the complete
registered package. The manifest continues to include every registered file.
Scaffold validation requires the new selector file.

## Exact implementation

Base commit: 7fb377561e87735bd0a02f1d08160475e99c2559.
Initial source commit: 237ff68f75eee049aef52f6e8bf18abc5efb9c83.

| File | SHA-256 |
| --- | --- |
| src/aios/three_d_web/contracts.py | 76b94599cb6329bb517b03343c709dd40cb4c1647cb3b61916b644a26a7b3cc7 |
| src/aios/three_d_web/scaffold.py | 0fdca0809cdaa6e3b61f430fd9abcb971c691ac174e7293f5360b70211cf12a4 |
| src/aios/three_d_web/lifecycle.py | cac42122a0da099403455f8b2e8b7ee397e46afc6e1516a94c6c3a9094556d20 |
| tests/test_phase30c_profile_asset_selection.py | a6bb3018148fa6513f5b02433ca97b432698204c1558fc1e634fa7bb741f28a3 |
| .github/workflows/final-validation.yml | 1e7b5209b81fcfcd621cd523bd4913bbdcdbb91f9ec56eca9a2a8466fbebde7c |

## Executed validation

Focused repository pytest under CI=true passed 33 tests and 8 subtests with zero
skips, using Python 3.12.14, pytest 9.1.1, and Node 24.19.0. An independent review
reran the same suites successfully and separately exercised 21 actual generated
TypeScript selector cases.

The unchanged phase30a, phase30b, phase30c, and phase30f suites ran alongside the
new profile-selection suite. New checks execute the emitted TypeScript and
generated blueprint and cover profile-specific paths, deduplication, registry
order, legacy behavior, malformed groups, and an actual 7 MiB GLB rejected by the
6 MiB low-power budget. The equivalent legacy lazy-proxy asset retains its
previous budget behavior.

Node 24 is added to the Core CI job so the generated TypeScript checks run there.
A negative missing-Node invocation under CI=true produced the expected hard
failure instead of silently skipping those checks.

The five-file source manifest has SHA-256
eaa05a6bd0f55bfcee94f5c051b543d9db3f51add4066d49f635ab44f797a6c5.
The focused local test record has SHA-256
8ba3f4343a0eeda84cb48322a8e84bc1caefdfb06ff4b2268f61d6ead25e1a02.

## Acceptance boundary

This receipt records source behavior and focused local checks. The full GitHub
validation for PR #947 is pending at receipt creation. A complete generated-app
build and browser/WebGL acceptance of this product patch are separate gates.

Earlier isolated Blender/LOD fixture and browser evidence does not by itself
establish that this product patch was built or deployed. This change does not
provide arbitrary-asset optimization/compression, physical-device performance,
production deployment, current-generation authenticated recovery, durable
worker recovery, 72-hour NS12 acceptance, capacity acceptance, or full FR16/final
release acceptance. No production runtime or provider configuration changed.
