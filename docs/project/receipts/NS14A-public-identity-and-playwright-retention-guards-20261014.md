# NS14A — fail-closed live Portal identity and browser evidence retention — 2026-10-14

**Project:** AIONEX AIOS only. **Prepared host:** NEW `nc-ph-4354`. **Exact source base:** protected main `12a0da139269f2982992556289a666c572644f74`.

## Defect proved by the actual production release attempt

The previous PR #925 portal image passed source and six private-canary Playwright cases but **failed the actual public-endpoint acceptance 3/6**. The guarded release correctly rolled back to `web-dashboard-portal:release-960dab80`. All three failed Playwright cases referenced screenshot, trace and error-context attachments (nine total); the ephemeral runner had been removed before the attachments were saved, leaving the root cause indeterminate. The rejected image must **not** be rerun or redeployed to recreate this effect.

Two useful root-only NEW-host operator guards were already developed and tested privately. This PR introduces reviewed, separately testable copies into the protected AIOS source tree, hardened for fail-closed acceptance.

## 1. Public-source and cached-asset identity gate

`scripts/release/ns14a_verify_portal_public_artifact.py` checks the exact running Portal image ID, internal Next.js BUILD_ID and conversation route chunk name/SHA256, then fetches the current public HTML and its referenced chunk and verifies that the public immutable artifact matches.

Security and operational boundaries:
- Only HTTPS `ai.vip-e.net` and the six official locale conversation routes are accepted; no localhost, IP hosts, embedded credentials, foreign-origin redirects or external script URLs.
- HTTP reads are bounded to 8 MiB and 30 seconds; subprocess operations time out; no public POSTs or credentials.
- Expected image ID, BUILD_ID, chunk basename and SHA256 must have strict formats; ambiguous or missing assets fail closed.
- An optional evidence receipt is create-only `0600` with `O_NOFOLLOW`, `O_EXCL` and `fsync`, preventing accidental overwrites of previous acceptance evidence.
- This proves an artifact **identity subgate**, not customer authentication or release readiness.

Read-only live NEW-host test against the actual current old production Portal:
- Verified original `web-dashboard-portal:release-960dab80` public-image/BUILD_ID/chunk/hash: **PASS**.
- Supplied the quarantined PR #925 candidate's expected identity against the unchanged live old Portal: **FAIL_CLOSED, six mismatches**.
- No production images, DNS, tunnels, services or user data were changed. Root0600 output under `/var/lib/aionex-migration/r1-management-20261008/NS14A-SOURCE-GUARDS-20261014T1125Z/`.

## 2. Original six-case Playwright artifact retention gate

`scripts/release/ns14a_validate_playwright_artifacts.py` and `scripts/release/ns14a_collect_playwright_container_artifacts.sh` require exactly **six** original NS14A results and prevent stopped test runner deletion until the JSON report and all referenced screenshot, trace and error-context artifacts are saved and independently validated. Paths must remain inside the private evidence tree; zero-byte, symlinked, out-of-tree or missing artifacts cause failure. Dangerous runner names, labels and output paths are rejected.

Most importantly, **`retention_gate_passed` and `all_original_tests_passed` are separate values**: preserving screenshots of a failed test does not make the release green. The shell script does not weaken Playwright, modify browser tests, or introduce retries, test-order changes or acceptance bypasses.

Validation of the previous real rejected 3/6 JSON (read only) returned expected failure: three failed cases, nine missing attachments, `retention_gate_passed=false`. Unit tests also cover complete evidence retention for an unsuccessful test, confirming it remains a failed release test.

## Source validation

- **24/24 targeted tests PASS**, including strict-origin/redirect/asset ambiguity cases, missing and empty evidence, path traversal, symlinks, source control against the original six-case JSON, and cleanup ordering.
- `bash -n`, Python compilation and `git diff --check`: PASS.
- No production container or virtualized FR09 instance restarted; no changes to the canonical project acceptance thresholds.

## Explicit outstanding launch gates

These guards are to be incorporated in a **future newly approved, independently built and cryptographically verified** Portal release. They **do not** authorize rerunning the quarantined PR #925 candidate, accepting failed Playwright, or performing a production deployment. Require complete exact-head GitHub protected CI, immutable release-image attestation, the actual six unchanged browser cases against the **real** public site with retained artifacts, owner-approved rollback, and all independent FR06/FR08E/FR24/FR09/NS12/OLD retirement approvals.

Release state remains **`FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED`**.
