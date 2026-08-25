# Phase 36M — Unified User/Owner Creative and Project Studio

Date: 2026-08-25
Status: local exit gate PASS; protected PR and Production deployment pending

## Implemented

- Unified six-locale user Studio at `/{locale}/studio` for governed production jobs, live queue/progress, provider mode, external cost evidence, safety status, retry/cancel, asset library, downloads, project attachment and revision history.
- Ten discoverable capability-family presets across software, prompts/text, design/image/branding, audio, video/motion, music/song, 3D/XR, courses, sector solutions and realtime. Families that belong to a specialized project workflow route to Projects instead of being misrepresented as a Studio department.
- Durable Owner Studio Governance using the existing `OwnerControlRecord` authority; no new migration was required. Owner controls enablement, eligible plans, daily quota, concurrency, retry ceiling and moderation for each capability family.
- Studio job admission enforces the Owner policy before a durable job is created. The policy version/source and moderation mode are retained in job metadata and max attempts inherit the Owner policy.
- 36M.1 is deliberately provider-neutral and fail-closed: external provider activation is not introduced by this gate and `max_cost_usd` must remain zero.
- Owner page `/owner/studio-governance` manages all capability policies without code or environment-file edits and records mutations through the existing audit authority.
- Course Factory is exposed as a real six-locale VIP Academy surface using the existing Phase 36J runtime/API. Discovery requires `academy:read`; create and review actions retain their existing `academy:write` / `academy:assess` boundaries, and non-eligible plans remain fail-closed.
- Mobile-first browser acceptance covers Owner governance, User Studio at 390x844 in `ar/en/fr/de/es/tr`, and the permission-gated Academy course-factory surface, including Arabic RTL, no horizontal overflow, queue/cost/safety/history/checksum/review evidence and zero final console errors.
- Existing Branding Studio output (`brand strategy`, `identity tokens`, `usage guide`) plus the unified asset library/revision history provide the governed brand-kit/history path required by the 36M product scope.

## Local acceptance

- Studio Backend/DB regression: 22/22 PASS on isolated PostgreSQL.
- Owner API/navigation/language contracts: 28/28 PASS.
- Unified Studio portal static contract: 4/4 PASS.
- Phase 36 governance: 15/15 PASS before registry closeout.
- Browser E2E: 4/4 PASS in disposable `network=none` Chromium container; Owner mobile governance, VIP six-locale Studio, Studio-to-Academy routing, and Academy mobile course-factory acceptance all PASS with explicit `playwright_exit=0`.
- Owner Arabic coverage: PASS (`991` strings).
- VIP TypeScript, ESLint and production build: PASS; Studio route emitted for all six locales.
- Owner TypeScript, ESLint and production build: PASS; `/owner/studio-governance` emitted.
- Ruff, focused Mypy and `git diff --check`: PASS.
- Detailed local evidence v2: `/opt/AIOS/.deployment-backups/phase36m-part1/20260825T152848Z/local-acceptance-v2.json` (`sha256:695fc95b5d37c91c9fe899ed46b84925ff30b5eb24b87465af317c6cef29d5fc`).

## Problems found and fixed

- PR #513 first CI round failed Core contracts because historical Owner/VIP page inventories were stale for the new Studio Governance, Studio and Academy routes; inventories/static portal contracts were updated. The first Frontend Build also failed Prettier on the new Owner page; the exact CI formatter was applied and passed locally.
- Academy discovery originally required both read and write permissions; it was corrected to `academy:read` only while write/review actions remain separately permission-gated.
- Strict VIP lint initially failed on one unused icon import; it was removed.
- Owner Arabic coverage identified four untranslated dynamic fragments; they were translated. Duplicate `Refresh`/`Enabled` catalogue additions then failed TypeScript and were removed in favor of the existing catalogue entries.
- Initial DB tests required real Organization/User fixture rows for audited Owner mutation and exposed a stale flattened-FastAPI route assumption; both test contracts were corrected. Owner page-count invariants were updated from 47 to 48 after the new page.
- Browser acceptance first exposed missing Portal/Security-Lab mocks, then an invalid null Portal configuration, then a standalone-test RSC prefetch mismatch. The final gate uses a valid neutral Portal configuration and the actual generated static-export RSC artifacts from `out/{locale}/index.txt`; both browser tests passed with explicit `playwright_exit=0`.

## Explicit non-claims

- No Production migration, Production application-data mutation, service restart or deployment occurred in this local gate.
- No provider credential or paid provider was activated; provider requests=0, GPU jobs=0, provider spend=$0.00.
- Existing external gates from 36G/36H/36I remain unchanged.
- These three 36M capabilities are `locally_executed`, not `runtime_verified`, until the protected PR merges and a separate Production deployment/acceptance gate passes.
