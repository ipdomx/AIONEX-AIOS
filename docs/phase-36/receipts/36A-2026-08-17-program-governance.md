# Phase 36A Receipt — Program governance, registry and reporting invariant

- Receipt ID: `P36-R-36A-20260817`.
- Batch: `36A`.
- Objective: make the expanded product contract machine-readable, expose truthful maturity states, and enforce reporting for future Phase 36 product changes.
- Production gap before change: Phase 36 existed as an authoritative roadmap, but there was no machine-readable maturity registry and no CI gate proving that Phase 36-owned code changes were accompanied by the required live report/receipt.
- Changed paths/services/schemas: core Phase 36 program registry, public capability endpoint, Owner finalization snapshot/UI, reporting checker/workflow, Phase 36 docs/tests. No database migration.
- Technology/version review: no new production runtime dependency is introduced by 36A; the batch uses Python standard-library dataclasses/JSON-compatible snapshots and the repository's existing FastAPI/Next.js toolchains. Runtime technology pins remain governed by the master roadmap and per-batch official-source refresh rule.
- Security/privacy/cost/sector review: registry contains no credentials or tenant data; capability status is product metadata only; public snapshot exposes no provider credential/account identifiers; reporting checker reads Git path names only. No billable provider call is introduced.
- Acceptance: unique capability IDs; every capability owned by exactly one 36A–36N batch; valid ordered maturity states; current batch must be 36B after 36A closure; user/public and Owner surfaces must expose the same snapshot; Phase 36-owned product changes fail CI without master-report/receipt/exemption evidence.
- Problems discovered:
  - Owner frontend shared-type regression: the new required `phase36` snapshot field was added to `/owner/completion` but initially missed the separate `/owner/finalization` empty-state initializer. TypeScript caught TS2741 before merge; the initializer was corrected and full Owner type/build regression was rerun. The root cause and prevention are retained as P36-0002 in the master ledger.
  - Local Full Backend harness attempt mounted `web-dashboard/backend` directly at `/app`, which broke a repository-relative Firebase test using `Path(...).parents[3]`. No application assertion ran. The rerun mounts the whole repository at `/workspace` and uses the same relative layout as GitHub CI; this is a local test-harness issue, not a product defect.
- External activation gates: unchanged; 36A is governance only.

## Pre-merge validation evidence

- Core Phase 36 + historical completion contracts: `15 passed`.
- Full AIOS Core suite after final 36A registry change: `720 passed`.
- Backend public Phase 36 capability endpoint contract: `1 passed`.
- Backend static quality: Ruff PASS; Mypy PASS across `178` source files.
- Full Backend from a fresh PostgreSQL 16 + Redis environment migrated from zero to Alembic `20260816_0027`: `629 passed, 1 skipped, 0 failed`.
- Owner frontend: Arabic coverage `922` translatable strings / `5` approved technical tokens; TypeScript PASS; Owner lint PASS; Prettier PASS; production build `86/86` pages; dependency audit `0 vulnerabilities`.
- VIP frontend: integrity `90` files / `6` complete locales; TypeScript PASS; lint PASS; static build `115/115` pages; static smoke `94` URLs; dependency audit `0 vulnerabilities`.
- Browser E2E on production frontend builds: `10/10 passed`, including the Phase 36 user status card at a 390px mobile viewport, campaign readiness guards, RTL/mobile overflow and Owner boundaries.
- Phase 36 reporting checker negative/positive contracts prove an owned code change fails without roadmap/receipt/exemption evidence and passes when a receipt is present.
