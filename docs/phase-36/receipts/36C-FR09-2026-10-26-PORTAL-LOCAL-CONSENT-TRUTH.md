# Phase 36C / FR09: truthful localized local-Free project consent

**Ledger:** P36-0092. **Date:** 2026-10-26. **Source only, no production deploy.**

## Observed user-portal mismatch
- The existing Full Project button always opened the paid/external governed
  project confirmation text and displayed an external AI provider budget of
  USD 0.05, even for users on the Free local-only Owner policy.
- The API client also hard-coded confirm_external_processing=true whenever
  mode was full or 3d_full, regardless of the actor's locally scoped plan.
- The backend Free project route in PR #994 is designed to resolve the
  *effective* Owner policy and persist provider=ollama, budget=0 and
  external_processing_confirmed=false for approved local Free projects.
  An incorrect frontend prompt would still misrepresent the action despite
  backend policy enforcement.

## Source-only user experience correction
- Use a known Free status from existing current FreeTierStatus and the
  authenticated user's organization.plan / role metadata.
- When Free, show a dedicated localized confirmation that Ollama MODEL
  processing is local, external AI provider cost is 0, and final governance
  and release approval are still required. Avoid claiming *all* project
  infrastructure and user data stay exclusively on one physical host.
- Pass confirm_external_processing=false only for the Free full project
  action; for non-Free Full or 3D routes preserve their preexisting explicit
  window.confirm prompt and true external confirmation. The backend must
  independently verify effective Owner policy and never trust client flags.
- Preserve provider-neutral contract and all remaining API client defaults.
- Add six dedicated translations for ar, en, de, es, fr, tr, without removing
  or altering legacy Paid/3D confirmation strings.

## Verification
- Portal TypeScript tsc --noEmit --incremental false PASS in offline,
  read-only Node 24 production image with the existing pinned dependencies.
- ESLint --max-warnings=0 PASS on the complete portal tree under no-network
  read-only container.
- Node locale/integrity verifier PASS: 105 files, six complete locales,
  no simulated data markers.
- Four pure source regression tests, plus 17 Phase36 governance tests,
  PASS. Assertions check both Free and Paid branches, 3D preservation,
  explicit outbound consent flag, and six translation fields.
- Protected GitHub CI and a separate controlled portal release remain
  required. No production portal image is modified by this change.

## Release boundary
- No customer rows, provider secret, payment setting, currency balance,
  paid inference, Backend/FR25 generation, container or DNS setting changed.
- This source-only UI correction does NOT certify one real project
  completion, actual5000 active user proof, 15000 durable real model
  completions, independent FR08 acceptance or a clean 72h FR25 window.

**Full release: HOLD.**
