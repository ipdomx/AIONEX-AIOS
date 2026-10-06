# NS-15 continuity, exact-SHA and client-delivery policy — 2026-10-06

Status: **reviewed documentation candidate; no production mutation**

This receipt records three controls requested during final-release continuation:

1. **Client delivery/stream resilience is now explicit release scope.** The observed external ChatGPT “streaming interrupted” UI is not treated as proof of an AIOS defect. Instead, the analogous AIOS failure class is made a required acceptance item: durable job identity, bounded timeout/heartbeat, reconnect/resume or durable-status fallback, idempotent de-duplication, no duplicate provider charge/execution, and explicit reconnect/recovery/failure UI states.
2. **New-server operation is exact-SHA bound.** MCP2 may enter through the retained management host and then use the approved SSH administrative channel with strict host-key verification to the new server. GitHub exact SHA is resolved before mutation; a clean SHA-bound worktree/checkout is used; exact-head CI is not reused for a different commit; rollback images/source are preserved; live runtime identity and health are reverified after rollout. No credentials, private key material or raw host secrets are documented.
3. **Every material state transition is retained.** PASS, FAIL, BLOCKED/HOLD, PENDING_RETRY, ROLLBACK, IN_PROGRESS and COMPLETE are preserved in the runtime journal/checkpoint with SHA/evidence/next-action fields. The canonical map is the reviewed summary and is reconciled at material checkpoints rather than on every transient CI poll. Generated STATE.json and PROJECT-REPORT.md remain project_hub outputs only.

The anti-stall/reconnect source is merged from PR #872 at exact head `d17c54530c9142f04bbf9aab50a1df01f5abe926` as merge commit `9dd7a79d3b590a25675d5209de14b5176cba7f7f`. Protected exact-head CI is PASS, focused conversation/contract acceptance is 45 PASS and the exact-head core suite is 4472 PASS. This is still **not** a production-runtime acceptance claim: exact protected-main rollout and durable reconnect/anti-stall smoke remain required.

Current security reconciliation note: protected main exposes 2 patchable VIP Dependabot alerts (source-map-js and postcss-selector-parser). Four Trivy Docker-module source-manifest alerts were dismissed as not-used only after exact FR-23 binary/module reachability PASS proved they are not linked and no patched module release exists.

Security reconciliation update: PR #875 merged at `704a79cf3c98b70b526fa9c08eb1b88bd1221096` with protected CI PASS, pinning the two patchable VIP dependencies to fixed versions. The accepted tree has `npm audit --omit=dev = 0`. Dependabot still showed those two alerts open immediately after merge, so NS-15 records index reconciliation as pending instead of claiming the queue is already empty.

Dependabot index reconciliation completed after PR #875: protected `main` now reports **0 open Dependabot alerts**. The four prior Trivy Docker-module findings remain documented as evidence-backed not-used dismissals from exact binary/module reachability; this closes the current alert queue without asserting absolute security.
