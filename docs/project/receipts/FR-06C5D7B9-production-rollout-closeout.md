# FR-06C5D7B9 — Production ZAP exclusivity closeout

This receipt reconciles the tracked FR-06 map with the latest live Production state after the protected B9 source merge.

PR #746 merged as `3a9298022086ad7c8ab09e77e6d81e564323d5d4` after all protected candidate checks passed, and all five post-merge `main` workflows completed successfully. The server source is synchronized and clean on that commit.

Production ZAP exclusivity is now verified. The live environment was re-read without exposing credential values: the only running containers with non-empty ZAP-related variables are `security-scan-worker`, which retains `SECURITY_ZAP_URL` and `SECURITY_ZAP_API_KEY`, and `security-zap`, which retains only its API key. Neither service has host port bindings. The accepted Production guard remains before any direct `ZapClient()` construction, so Production fails closed when no durable `ScanResourceRuntime` is supplied. No real ZAP scan was required for this closeout.

The current Production database remains at Alembic head `20260920_0062`. The latest maintenance-authority verification after the B9 rollout shows schema 7 open at generation 13 for the seven existing scopes. A prior B9 acceptance event at generations 10→11 remains valid historical evidence; the later generations 12→13 are the current runtime state and therefore supersede it only as the current authority/topology reference.

During the later live verification, Compose dependency recreation also recreated the PostgreSQL container and its initialization dependencies even though no database migration or intentional data change was requested. PostgreSQL returned healthy on the retained persistent database, the Alembic head remained `0062`, and the application runtime returned to 36 running containers, 35 healthy containers, zero unhealthy containers, with Cloudflare and the Realtime/ZAP daemon infrastructure unchanged. This later container identity is the current Production topology and should be used for future comparisons instead of the earlier B9 container-ID baseline.

B9 does not claim Realtime/LiveKit ownership, Egress drain, token expiry, session drain, legacy ambiguous-work settlement, or full-host closure. Those remain FR-06 work after D9A and later runtime-ownership/drain parts.
