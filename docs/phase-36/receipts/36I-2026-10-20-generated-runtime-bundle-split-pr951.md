# Phase 36I — generated 3D runtime bundle split and PR951 CI repair receipt

Status: **source-only verification PASS; fresh original CI pending; production unchanged**.

## Scope

- Pull request: `#951` (`fix/fr16-bundle-split-20261020`).
- Protected-main base: `3425a43ad0edc65c885fa37a1cdf53551dc46563`.
- Original failing head: `d55ff9f38c401c12167c407f1bc9bb90bf702f42`.
- The source change splits generated React, React Three Fiber, Drei, Three core/renderer, and `three-stdlib` bundles while keeping the 500 kB warning threshold unchanged.
- The regression test requires the split and rejects hiding the warning through `chunkSizeWarningLimit`.

## Preserved local verification

- Source tests: 66 passed, 4 skipped, and 8 subtests passed without weakening source or tests.
- Isolated network-none Vite build: 603 modules transformed, seven JavaScript chunks, largest chunk 379,729 bytes, all JavaScript chunks below 500,000 bytes.
- Browser smoke: desktop, mobile, and low-power profiles passed with no page, console, request, or external-network failures.
- Authoritative evidence: `/var/lib/aionex-migration/launch-continuation-20261020T2234Z/FR16-BUNDLE-SPLIT-SOURCE/SOURCE-BUNDLE-SPLIT-PROOF.json`.

## Original-CI findings repaired

Final Validation run `39510051346` exposed two real failures on the immutable original head; no job was rerun:

1. Phase 36 reporting job `118928534240` rejected `src/aios/three_d_web/scaffold.py` because the PR had no tracked Phase 36 receipt. This receipt supplies that required source-reporting evidence.
2. Dependency Security job `118928534485` rejected `follow-redirects@1.16.0` for high-severity credential-header disclosure advisories `GHSA-q3jh-wrc6-jgq8` and `GHSA-8r9p-f939-6h3c`. The frontend lock now resolves the transitive package to patched `1.16.1`; `package.json` is unchanged.

The downloaded npm tarball was verified before updating the three lock fields:

- artifact: `follow-redirects-1.16.1.tgz`
- bytes: `10076`
- SHA-512 hex: `14dbc51b3a0c2d6984e988fdb296ffce377bca23421e2016f7f4e0f425eb43cc2ebb7d87b6524ec163b5d4e25a7e5e457d8dc3c53750d2f8f8db353592fbf98e`
- npm SRI: `sha512-FNvFGzoMLWmE6Yj9spb/zjd7yiNCHiAW9/Tg9CXrQ8wuu32HtlJOwWO11OJafl5FfY3DxTdQ0vj42zU1kvv5jg==`

## Acceptance boundaries

- This receipt does not claim fresh CI success, merge, deployment, or production runtime acceptance.
- No production Docker, PostgreSQL, Redis, DNS, SSH, provider, or credential mutation occurred.
- It does not accept full FR16, FR08E/full recovery, final release, or the actual 5,000-user gate.
