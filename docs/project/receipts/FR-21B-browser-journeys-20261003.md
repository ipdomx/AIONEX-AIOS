# FR-21B Browser Journeys Acceptance Receipt — 2026-10-03

## Scope
This receipt covers only the FR-21-owned browser acceptance preparation in run `fr21-scheduled-20261003T162150Z-6ac0f32b-r7`.

Owned paths in the retained claim:
- `tests/browser-e2e/specs/owner.spec.ts`
- `tests/browser-e2e/specs/vip.spec.ts`
- `docs/project/receipts/FR-21B-browser-journeys-20261003.md`

No shared Playwright package/config file, live hosting, Cloudflare tunnel, database, provider, key, service, user history, or user data was changed.

## Current authority and source identity
- Continuation authority: current POLICY.md section **Fresh Owner all-worker repair window after 2026-10-03 17:05 UTC**
- Current policy SHA-256: `50b7f0cf10d2071515ffa20c02d3789b528fbfa86dc35e7cd89ad7d953e4cfee`
- Retained worktree branch: `auto/parallel-20261002-v1/fr-21/fr21-scheduled-20261003T162150Z-6ac0f32b-r7`
- Retained source base / worktree HEAD before this commit: `109492b3ddfa0838e4330934679011e14bd668c3`
- Current observed `origin/main`: `6544fa5f363c2fbbe8814567395608bcd70c1725`
- Integration/live/final FR-21 closure remains gated by unfinished dependencies and coordinator acceptance.

## Preserved shared browser harness
The shared harness remained byte-identical to both the retained source base and current `origin/main` during this validation:
- `tests/browser-e2e/package.json`: `fb5b292dcec73d3ccf5aecf953effa6bd5c8e75abc82f95518df75263d02df72`
- `tests/browser-e2e/package-lock.json`: `2dba78a7bd1a09518deb1aadc029ce9d8419393c52ba9ad1583e64cc8bbbbde9`
- `tests/browser-e2e/playwright.config.ts`: `cd23375b7b618421abbaa61d4341d8664ef9f6b48d4c34a0a30e994df1670439`

## FR-21-owned assertions prepared

### Owner dashboard negative-permission boundary
`owner.spec.ts` adds an authenticated ordinary Organization Owner journey that verifies:
- `/owner/production-runtime` is intercepted by the existing `SuperOwnerGuard`;
- the page renders `Super Owner access required`;
- the user can return to the normal dashboard;
- protected `Production Runtime` content is not rendered;
- no protected `/api/v1/owner/production-runtime` request is emitted before the guard denies access.

Current file SHA-256: `39b52443ffb90b6bbbb5b17fa36faf7a9d741e85fd4464065b1a75128e4c2f13`

### User dashboard projects / conversations / download acceptance
`vip.spec.ts` adds FR-21-owned journeys that verify:
- Projects navigation reaches the protected Project Conversations surface;
- only documented read contracts are exercised for `/project-conversations`, `/project-conversations/policy`, and `/project-conversations/agents`;
- owner-policy `403` denial fails closed, shows an alert, disables `New conversation`, and emits zero mutation requests;
- approved Academy ZIP download preserves the server-provided `Content-Disposition` filename.

Current file SHA-256: `10eca0266d5c15023889ec4feac26eb5de194c8ee0958df179b3337c8ab75a6a`

## Isolated validation performed
After exact FR-21 reservation verification, the previously blocked isolated browser harness operation was retried once under the newer Owner repair window:

```text
npm ci --ignore-scripts --no-audit --no-fund
npx playwright test specs/owner.spec.ts specs/vip.spec.ts --list
```

Result:
- `npm ci`: PASS (3 packages installed, no package/lock/config edits)
- Playwright collection: PASS
- Collected: 19 tests in 2 files
- Newly prepared FR-21 assertions are discoverable:
  - authenticated organization owner cannot cross the Super Owner dashboard boundary
  - projects links into the protected conversation surface and loads only the documented read contracts
  - conversation permission denial fails closed and never emits a mutation
  - approved Academy download preserves the server Content-Disposition filename
- `git diff --check`: PASS

This is truthful collection/static harness validation only; it is **not** a claim that the full hosted browser journeys, Safari/WebKit/iPhone acceptance, dependency integration, or FR-21E hosted-source fingerprint acceptance are complete. Those remain coordinator/dependency gated.

## Production impact
`production_changed=false`

Recorded at `2026-10-03T17:23:08.133714+00:00`.
