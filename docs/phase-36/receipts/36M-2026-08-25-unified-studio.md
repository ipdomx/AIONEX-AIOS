# Phase 36M — Unified User/Owner Creative and Project Studio

Date: 2026-08-25
Status: enhanced local exit gate PASS; protected PR #513 update and Production deployment/acceptance pending

## Implemented

- Unified six-locale user Studio at `/{locale}/studio` for governed production jobs, live queue/progress, provider mode, external cost evidence, safety status, retry/cancel, asset library, downloads, project attachment and revision history.
- Ten discoverable capability-family presets across software, prompts/text, design/image/branding, audio, video/motion, music/song, 3D/XR, courses, sector solutions and realtime.
- Capability launch behavior is now truthful and fail-closed instead of treating every family as a generic Studio department:
  - Studio-native families launch the existing durable Production Studio runtime.
  - Courses launch the real user Academy/Course Factory surface at `/{locale}/academy`.
  - Sector solutions launch the in-Studio Phase 36L sector launchpad backed by the verified reusable sector packs and Domain Blueprint v3.
  - Music/song remains visible but not runtime-launchable while its external provider/funding/rights activation gates remain unresolved.
- New six-locale user Academy/Course Factory surface at `/{locale}/academy` reuses the existing Academy backend authority and supports:
  - durable course creation;
  - six-locale package generation (`ar/en/fr/de/es/tr`);
  - queued/building state polling;
  - package version/history evidence;
  - SHA-256 archive evidence;
  - permission-scoped approve/reject review;
  - authenticated ZIP download.
- Academy access is consistent with the existing backend authority: Free is not a supported Academy plan, `academy:read` is required for discovery/read access, `academy:write` controls creation/build actions, and `academy:assess` controls approve/reject actions.
- Studio sector launchpad exposes the nine verified Phase 36L reference packs plus a lawful custom-sector path. A selected pack creates a normal tenant Project in a selected Workspace with the Domain Blueprint v3 evidence retained in the project specification; no paid provider or automatic external execution is introduced.
- Durable Owner Studio Governance uses the existing `OwnerControlRecord` authority; no new migration was required. Owner controls enablement, eligible plans, daily quota, concurrency, retry ceiling and moderation for each capability family.
- Owner Governance now receives immutable runtime truth (`supported_plans`, `required_permissions`, `runtime_launchable`, `activation_reason`) and prevents selecting plans that the underlying runtime does not support. A policy toggle cannot bypass an external runtime gate.
- Studio job admission enforces the Owner policy before a durable job is created. The policy version/source and moderation mode are retained in job metadata and max attempts inherit the Owner policy.
- 36M remains provider-neutral and fail-closed: external provider activation is not introduced by this gate and `max_cost_usd` must remain zero.
- Owner page `/owner/studio-governance` manages capability policies without code or environment-file edits and records mutations through the existing audit authority.
- Mobile-first browser acceptance covers Owner governance, User Studio and User Academy. Studio is exercised at 390x844 in `ar/en/fr/de/es/tr`; Academy is exercised as a permission-gated mobile surface with review evidence and no horizontal overflow.
- Existing Branding Studio outputs (`brand strategy`, `identity tokens`, `usage guide`) plus workflow presets, the unified asset library and durable revision history provide the template/brand-kit/asset-history path required by the 36M product scope.

## Current local acceptance

- Initial Studio Backend/DB regression before the Academy/activation refinement: 22/22 PASS on isolated PostgreSQL.
- Post-refinement Backend runtime acceptance: PASS inside the exact `aionex-aios-backend:local` image after migrations through Alembic `20260825_0043`, against disposable PostgreSQL 16. Evidence asserted:
  - `academy:read` on an eligible paid plan -> available;
  - missing Academy permission -> `permission_required` fail-closed;
  - Free Academy access -> `plan_not_supported` fail-closed;
  - Music/song -> `external_activation_required` fail-closed;
  - Owner attempt to include unsupported Free in Course policy -> rejected as `invalid_policy`.
- Phase 36M portal contract + Phase 36 governance regression: 23/23 PASS.
- Completion-program regression: 8/8 PASS.
- VIP `verify:static`: PASS — integrity, TypeScript, ESLint, production static build and 94-URL smoke. Build emitted 127 static pages including `/{ar,en,fr,de,es,tr}/academy` and `/{ar,en,fr,de,es,tr}/studio`.
- Owner TypeScript: PASS.
- Owner Arabic coverage: PASS (`991` translatable UI strings; `5` approved technical tokens).
- Owner production build: PASS (`89/89` static pages), including `/owner/studio-governance`.
- Phase 36M browser acceptance: 4/4 PASS in headless Chromium:
  - VIP six-locale mobile Studio/runtime evidence;
  - Studio -> Academy discoverability;
  - permission-gated mobile Academy/Course Factory surface;
  - mobile Owner Studio Governance.
- Backend governance source/test modules compile: PASS.
- Full backend static quality after protected-PR follow-up: Ruff PASS and Mypy PASS across `245` backend source files.
- `git diff --check`: PASS.
- Initial detailed local evidence remains at `/opt/AIOS/.deployment-backups/phase36m-part1/20260825T150506Z/local-acceptance.json` (`sha256:3ff39633ad1a1a688f98d3caa098f9d4af4f81b6d79bfc714de690602fa5fa17`).

## Problems found and fixed

- PR #513 second CI round exposed one full-backend Mypy-only error in `studio_governance.py`: `phase36_program_snapshot()` correctly returns `dict[str, object]`, so the known `batches/capabilities` payload now uses `typing.cast` for static narrowing. Runtime behavior is unchanged; exact Ruff + full Mypy gates pass locally.
- The first local 36M exit had a product-level gap: the Studio Course preset had been changed to route to `/{locale}/academy`, but no VIP Academy page existed. A real user Academy/Course Factory surface was added before protected merge.
- Capability availability originally allowed Owner policy to express plans that a specialized runtime could not honor. Runtime-supported plans and permission requirements are now explicit and enforced both in the backend and Owner UI.
- Music/song previously risked appearing like an ordinary project launch even though 36G evidence still contains external provider/funding/runtime gates. It is now explicitly visible-but-gated and cannot be activated by an Owner toggle alone.
- Sector solutions originally fell back to generic Projects. They now expose the actual verified Phase 36L reference pack catalogue and Domain Blueprint v3 project launch path.
- Owner Arabic coverage caught three new runtime-gate strings; they were added to the shared translation catalogue rather than suppressing the check.
- Browser acceptance exposed a static-export trailing-slash assertion and a strict locator collision; both test harness issues were corrected. The current browser gate is green.
- The production backend image intentionally does not ship `pytest`; therefore the post-refinement backend gate was executed as direct runtime acceptance in that exact image against disposable PostgreSQL rather than falsely claiming a pytest run. The disposable database, network and temporary acceptance script were removed after the PASS.

## Explicit non-claims

- No Production migration, Production application-data mutation, service restart or deployment occurred in this enhanced local gate.
- No provider credential or paid provider was activated; provider requests=0, GPU jobs=0, provider spend=$0.00.
- Existing external gates from 36G/36H/36I remain unchanged.
- Music/song remains intentionally gated until its external activation requirements are independently satisfied.
- The protected PR must merge and a separate Production deployment/acceptance gate must pass before 36M may be described as Production-verified.
