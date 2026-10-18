# Phase 36I — finite 3D performance evidence admission

Date: 2026-10-18 UTC
Scope: FR16C performance sample validation and direct performance receipt construction.

## Reproduced problem

The current PerformanceSample.validate implementation rejected negative numbers
but admitted NaN. Comparisons against the unchanged performance budgets then
produced no violations for that metric. A pure-function execution against the
current source reproduced a passing gate separately for NaN in all seven fields:

fps, frame_time_ms, draw_calls, triangles, asset_bytes, bundle_bytes, and
gpu_memory_mb.

PerformanceReceiptBuilder.build also accepted a sample directly without calling
its validator. A caller could therefore construct a receipt from invalid sample
values even if it did not evaluate that sample through PerformanceGate first.

## Change

Validate finite values for all seven numeric sample fields before the existing
nonnegative checks. Reject NaN and positive/negative infinity with a field-specific
ValueError. Python integers are treated as finite without float conversion, so
large finite integers continue to reach the existing budget comparisons.

The optional gpu_memory_mb=None value keeps its prior behavior: sample validation
permits it, and PerformanceGate reports the missing metric when its selected
budget requires one. The timing_measurement_authoritative flag retains its
existing budget-comparison behavior; it does not permit nonfinite measurements.

Call sample.validate at the direct receipt-builder entry point as well. Existing
performance budgets, limit comparisons, release requirements, and valid receipt
serialization are unchanged.

## Exact source

| File | SHA-256 |
| --- | --- |
| Baseline src/aios/three_d_web/performance.py (8,062 bytes) | 88a522e4d9abe3e910a4d81b7bfc07768894f693f87994406440e0e35dd390a3 |
| Candidate src/aios/three_d_web/performance.py (8,607 bytes) | 8585f9aa99668933d2b31102f8a95419b3ec5b8a070ffbd2015ce7657625e649 |
| tests/test_fr16c_performance_finite_admission.py (2,908 bytes) | 4ab45404d5b8f1686650b66c617a72a98de05bc9fd1373a028f792c4de825c26 |

## Executed verification

Targeted repository pytest completed at 2026-10-18T11:57:57Z:
**79 passed in 0.32 seconds, no skips**.

The existing eight tests cover representative profiles, budget violations,
missing required GPU telemetry, negative values, deterministic receipts, and
release requirements. The 71 new cases cover:

- 42 gate rejections: seven fields, three nonfinite values, both timing-authority settings.
- 21 direct-receipt rejections: seven fields and three nonfinite values.
- Seven large finite integer cases through unchanged comparisons and receipt construction.
- One finite timing case confirming the original authoritative/nonauthoritative distinction.

An independent local compatibility check compared 14 finite fixtures and found
identical baseline/candidate gate results and receipt bytes/hashes. It included
three normal profiles, three missing-GPU cases, finite nonauthoritative timing,
and seven large-integer cases. That check used a pure module loader with an
explicit enum-only dependency scaffold; it is separate from the actual repository
pytest execution above. AST comparison also retained the original budgets, gate
comparisons, release gate, and serialization body.

## Retained evidence

Private evidence is under:
`/var/lib/aionex-migration/r1-management-20261008/CONTINUATION-20261018T1040Z`.

| Evidence | SHA-256 |
| --- | --- |
| FR16-PERFORMANCE-FINITE-PYTEST.json | 26c1647e1fce9b98aa8b077010f90ec6247f2c0d37fb861760ddd90ee2673033 |
| FR16-PERFORMANCE-FINITE-LOCAL-PURE-CHECK.json | 794df9d049176f5e20c0f55fd517aba828227c6aed72703195d2f499ae389a00 |

The root reproduction is retained as FR16-PERFORMANCE-NONFINITE-BASELINE.json.
It records seven baseline NaN false passes with the original source hash.

## Acceptance boundary

This fixes input admission for performance measurements and their receipts. It
does not provide new measured FPS/GPU results, optimization/compression/LOD output,
production asset delivery, recovery evidence, Hunyuan approval, or full FR16 or
release acceptance. Validation performed no provider requests, load test,
production deployment, restart, or production configuration change.
