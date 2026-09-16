# FR-06C3C5 — guarded empty Redis cutover executor

Status: source only; production is unchanged by merge.

The executor binds the exact running Redis-client topology and a fresh recovery point to a single-use plan. It requires all durable jobs, realtime sessions and LiveKit rooms to be zero before the window. It then stops every captured Redis client before Redis, retains the legacy Redis volume read-only as evidence, and starts the encrypted operations-vault candidate with **no AOF copy**. `DBSIZE=0` is a hard gate before any client may return. Only clients that were running before cutover are recreated, at their exact prior scale.

Failure semantics deliberately differ before and after client restart. Before any candidate client starts, no Redis divergence exists, so the exact quiesced legacy Redis runtime may be restored. After any candidate client starts, the executor stops the candidate topology and fails closed; it never copies candidate AOF back and never blindly resurrects the stale legacy AOF. Recovery then requires the explicit empty/reconciliation path.

This executor does not move retained host logs; that acceptance remains in C3E. It does not open application admission or alter Cloudflare.

The official Redis image was independently observed to normalize a freshly mounted `/data` root to mode `0755` on its first start. The executor therefore requires the candidate to prove `DBSIZE=0`, then re-hardens the mapper-backed Redis subpath to `0700` with owner `999:1000` **before any application client is restarted**. Failure to retain that boundary is a pre-client cutover failure and follows the safe legacy rollback path.
