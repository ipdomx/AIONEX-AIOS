# FR-18A — Phase29 / Project Builder acceptance inventory

Run: `fr18-scheduled-20261003T090026Z-6ac002cb-r13`
Task: `6ac002cb74408191909e804cc9b6312b`
Batch: `FR-18` / `FR-18A`
Base: `3b382d00bacb1db50bf532d5f085e85585f32006`
Production changed: **no**
Live/provider/store deployment performed: **no**

## What this run accepted

This run adds a dedicated, current acceptance matrix for the retained Phase29/core-business requirements and the project-builder families without replaying historical green suites.

The matrix verifies current deterministic source generation for:

- web + API;
- data pipelines;
- bots, while retaining the external messaging credential gate;
- desktop source, while retaining platform code-signing as an external gate;
- browser-extension source, while retaining store publication as an external gate;
- commerce source, while retaining live payment-provider credentials as an external gate;
- Android/iOS **source-mobile** generation, while retaining Apple/Google store credentials and signing as external gates;
- the bounded IoT simulator source, while retaining physical-hardware validation;
- the bounded robotics simulator source, while retaining robotics hardware/runtime validation.

Generated project profiles are required to keep `production_claim=false`. Generated security guidance explicitly keeps provider, store, signing, payment and hardware actions behind external activation gates.

## Core business requirements retained

The matrix also binds the current acceptance to retained Phase29 evidence for:

- accounts, organizations, workspaces, teams, roles, permissions, suspension and Super Owner authority (29C);
- plan/subscription-period, seat, limit and entitlement records without treating payment activation as FR-18 acceptance (29D);
- support, approvals, councils, ministries, policies and Owner controls, with unavailable channels remaining `unconfigured` rather than false success (29E);
- projects, tasks, workflows, reports, workforce, academy, knowledge and search, including the correction that provider-neutral snapshots are not full governed execution (29F);
- release gates that retain explicit Owner approval and operational evidence and never turn unimplemented host mutation into success (29G);
- mobile source/package evidence distinct from Apple signing/App Store publication (29H);
- plugins/integrations where missing credentials remain unconfigured/degraded rather than false green (29I);
- FR-18-owned controlled research and the governed full-project-cycle source paths.

No cross-scope implementation file was edited.

## Generic simulation boundary — still open

A current request `Build a deterministic simulation model` resolves to:

`web, api, domain, cli`

There is no generic `simulation` target in the current builder contract. The existing IoT and robotics simulators are bounded family-specific source and **must not** be counted as generic simulation acceptance, physical validation, or production execution.

Therefore FR-18A records generic simulation as:

`gap_generic_family_not_implemented`

This is an explicit remaining FR-18-owned criterion, not a false PASS.

## Own-run verification

Targeted new acceptance suite:

`tests/test_fr18a_phase29_builder_matrix.py`

Result after the final matrix expansion:

`15 passed`

Additional checks:

- `python3 -m py_compile tests/test_fr18a_phase29_builder_matrix.py`: PASS
- `git diff --check`: PASS
- `python3 -m ruff ...`: not executed because the current host Python environment has no `ruff` module; no package was installed and this is not reported as a source failure.

The earlier 14-pass result belongs to the pre-expansion version of the same new test and is not used as final acceptance evidence. A later formatting edit briefly introduced a literal `\\n` sequence that caused test collection and `py_compile` to fail; that deterministic FR-18-owned defect was corrected in the same file, after which the final 15-test run and compile/diff checks passed. Historical Phase29 test counts were not replayed.

## Remaining criteria

1. Generic simulation remains a real FR-18-owned source gap; any implementation requires a later fresh run/reservation for the relevant FR-18 builder source paths and dedicated tests. It must remain a deterministic/local source capability unless separately validated; it cannot be represented as physical or production execution.
2. FR-08 remains the dependency for integration/live/final FR-18 closure.
3. Only the coordinator may integrate this branch, update canonical PLAN/STATE/REPORT, or authorize deployment.
4. Platform application signing/store publication, payments, XR device validation and other deferred external activation remain outside this acceptance.
