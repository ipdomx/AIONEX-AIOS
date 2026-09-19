# FR-06D8C1 — Studio retained-evidence control boundary

Canonical receipt: `docs/project/receipts/FR-06D8C1-studio-control-evidence.md`.

Cancellation and retry inspect independent execution/publication/settlement
history after a fresh tenant-scoped job lock, before any reset or terminal claim.
The six previously failing regressions now pass in the 48-case isolated suite.
This is source-only control correction, not cancellation settlement, post-crash
cleanup, production activation or full-host closure. Exact acceptance and merge
state remain in `docs/project/runtime/events.jsonl`; no production migration or
service deployment is claimed here.
