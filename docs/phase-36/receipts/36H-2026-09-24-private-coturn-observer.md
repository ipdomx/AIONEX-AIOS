# 36H — Private Coturn allocation observation

FR-06C5D9B4B adds an actual read-only loopback allocation observer, pinned to Coturn image/container/process/network-namespace identity and bracketed by matching closed PostgreSQL authority reads. The source contract and real isolated CLI evidence are described in `docs/project/receipts/FR-06C5D9B4B-private-coturn-observer.md`.

Real disposable observations progressed from missing metric (rejected) to `[3, 3]` active allocations to `[0, 0]` after a test-only expiry, without restarting the observed process. No production metrics activation, service restart, migration, settlement or full-host/rollout authorization is asserted. The canonical Project Hub retains current CI, merge and operational state.
