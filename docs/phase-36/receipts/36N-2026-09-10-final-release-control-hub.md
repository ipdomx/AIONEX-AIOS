# 36N / FR-01 — canonical final-release control hub

The Owner directive, exact remaining batches, capacity contract and MCP2 repair receipt are now in `docs/project/PLAN.json`, `docs/project/README.md`, and `docs/project/receipts/FR-01-control-hub-mcp2.md`. This historical Phase36 receipt is a pointer, not another current report.

Source repair preserves 28 tools, corrects missing cwd, removes mutable-backup startup and hidden legacy RunPod aliases, confines restart to MCP2 systemd service, and handles timeout bytes before redaction. Protected merge precedes atomic install/live verification. No application service, Cloudflare, DNS, provider or deferred feature is changed by the candidate.

FR-00 PR604 is merged. FR-01 live status must be read from the canonical report/runtime journal, not inferred from the existence of this receipt.
