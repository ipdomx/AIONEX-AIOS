# 36N — Expanded launch operations closeout

Date: 2026-09-07
Owner scope order: AWS, Bedrock, XR and payment-provider activation are the final deferred batch. All other internally satisfiable launch work is active.

## G22 — historical communications debt

Production contained 23 terminal delivery rows older than 24 hours: 12 historical Email dead letters and 11 historical Push unconfigured rows. Every affected notification also had a successful/current delivery path, so the user-visible notification records were not archived or deleted. The 23 terminal delivery rows were reconciled in place with `historical_reconciled_at`, reason `launch-baseline-terminal-debt`, and `historical_actionable=false`; 23 audit events were written. Unreconciled historical terminal debt after the transaction: zero.

One Telegram delivery dead-lettered during the application-key rotation window because its endpoint still used the prior ciphertext. Both persisted communication endpoints were then re-encrypted under the new primary application key with audit events, verified 2/2 decryptable, and the affected Telegram delivery was requeued from the UID 1000 Communication Worker after its token readiness check passed. It subsequently reached `delivered`.

The Owner communications overview is updated to expose `actionable_by_status` separately from `historical_reconciled_by_status`. Production evidence against the reconciled dataset is: actionable = delivered only; historical reconciled = 12 dead-letter + 11 unconfigured.

## G27 — classified host cleanup

The two historical post-launch test containers were already absent. Sixteen anonymous dangling volumes were classified as detached CI/local-test PostgreSQL/Redis/empty volumes and removed explicitly. The named `aionex-ollama-phase22b-models` volume was preserved. Dangling images were pruned only when unreferenced; tagged rollback/candidate images were preserved. Build cache older than 24 hours was pruned; recent launch cache remains intentionally available for rollback/rebuild speed. No blind volume/system prune was used.

## G19 — independent availability monitoring authority boundary

An off-host GitHub-hosted five-minute availability workflow was prepared, but the repository credential available to the maintenance MCP is an OAuth credential without GitHub `workflow` scope. GitHub rejected the workflow-file push before any remote mutation. The existing on-host watcher remains healthy, but a true host-independent watchdog therefore still requires external GitHub workflow authority or another off-host monitoring account. This is not represented as internally complete.

## External/infrastructure truth retained

- Secondary RunPod cannot be armed internally: its secure file currently has no API credential and no endpoint/runtime image authority.
- Growth/Social has no connected user account rows. Meta/Telegram evidence remains real, but other provider live verification requires external OAuth/platform accounts; no account is fabricated.
- iOS has the product bundle ID but no Apple Development Team authority; App Store signing/association publication remains external.
- Multi-host HA, off-site backup replication, 1000-user realtime media capacity, and host disk encryption cannot be truthfully created from the current single 1-Gbps RAID1/ext4 host alone. They remain infrastructure/hosting authority boundaries, not hidden internal TODOs.
- WhatsApp remains an external account/token activation boundary.
- AWS, Bedrock, XR and payment-provider activation remain explicitly last by Owner instruction.
