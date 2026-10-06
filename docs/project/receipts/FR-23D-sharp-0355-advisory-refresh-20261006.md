# FR-23D — Sharp 0.35.5 advisory refresh (2026-10-06)

Status: **source candidate; protected exact-head CI required before merge/deploy**

## Trigger

After the accepted release 960dab80fe8ec27b1e8bf59425b766e03f9b9783, the npm audit service began reporting a new high-severity advisory against Sharp <0.35.5:

- package: sharp
- advisory: GHSA-wq5f-xc86-pv6w
- title: sharp : Vulnerability in librsvg dependency CVE-2026-96889
- patched release: 0.35.5

This advisory caused the Dependency Security job on documentation PR #876 to fail even though the PR changed documentation only. GitHub Dependabot had not yet indexed an open alert at discovery time, so the npm audit result is retained as the immediate trigger rather than waiting for a dashboard count.

## Candidate scope

The candidate updates active Sharp pins/contracts from 0.35.4 to 0.35.5 across:

- the governed image-derivative runtime and its exact-version assertions;
- the owner/frontend dependency override;
- the VIP dependency override;
- the Hunyuan3D Docker source pin without activating the deferred Hunyuan runtime;
- exact-version tests and Final Validation assertions.

Historical receipts/evidence that truthfully describe earlier 0.35.4 acceptance are intentionally not rewritten.

## Required acceptance

- regenerate npm lockfiles deterministically from the updated manifests;
- npm audit --omit=dev = 0 for web-dashboard frontend and image-tools;
- VIP production dependency audit = 0 for the patched tree;
- governed image-derivative targeted tests PASS;
- frontend/VIP integrity, type/lint/build contracts PASS where applicable;
- protected Security Baseline, Dependency Security, CodeQL, container/SBOM and Production Docker Build PASS on the exact candidate head;
- no production mutation before exact-head CI passes.

This is a dependency remediation receipt, not a claim of absolute security.
