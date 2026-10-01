# Phase 36N / FR-06 — Debian liblzma security floor

The isolated continuation of held #812 requires the official Bookworm liblzma fix for GHSA-5qpq-xqfv-j9pg: `liblzma5 >= 5.4.1-1+deb12u2`. Runtime package installation, file integrity, the actually mapped Python library and bounded offline compatibility are checked without changing detector rules, compiler locks, provider integrations, or production configuration.

Before correction the new source contract failed (23 companion cases passed). After correction 114 targeted cases passed, including 24 new cases. The original runtime OS stanza was built separately and rejected for its outdated package; the corrected OS-layer image passed nine native compatibility cases with no network, no capabilities and a read-only filesystem. These fixtures intentionally omit the complete scanner/application image. Allocator-failure corruption was not reproduced and whole-image security is not certified.

Detailed receipt: `docs/project/receipts/FR-06-security-lzma-backport.md`.
Server evidence: `/opt/AIOS/docs/project/runtime/fr06-os-package-review-20260930T1515`.

The existing blocked read of full-scan artifacts was not retried. The historical 200 HIGH/CRITICAL count is not reduced by assertion. Full Root/source matching and exact-head GitHub acceptance are separate evidence. Merge, deployment and live-source synchronization remain HOLD; FR-06, expanded capacity and final release remain open. FR-07 remains closed.
