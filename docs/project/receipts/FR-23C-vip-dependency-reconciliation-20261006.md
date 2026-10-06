# FR-23C — VIP dependency reconciliation candidate (2026-10-06)

Status: **locally validated candidate; wait for PR #872 merge before opening protected PR**

Base candidate: PR #872 exact head `48172753053e21d8adb09823b029453edfa49e05`.

This follow-up addresses the remaining VIP Dependabot entries that have patched versions:

- `source-map-js` is forced to 1.2.2.
- `postcss-selector-parser` is forced to 7.1.6.

Validation on the exact candidate tree:
- `npm audit --omit=dev`: 0 vulnerabilities.
- `npm ls source-map-js postcss-selector-parser --all`: both overrides resolve cleanly.
- VIP integrity check: PASS.
- VIP TypeScript type-check: PASS.
- VIP ESLint: PASS.
- VIP static production build: PASS.

The full development dependency audit still reports unrelated development-tool advisories; this receipt does not hide or close those. The four residual `github.com/docker/docker` Dependabot alerts belong to the pinned Trivy build manifest and remain subject to the already-recorded FR-23 binary reachability decision; they are not changed by this candidate.

No production mutation or provider call occurred.
