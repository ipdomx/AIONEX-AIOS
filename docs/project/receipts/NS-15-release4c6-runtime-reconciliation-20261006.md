# NS-15 — release 4c6 runtime reconciliation (2026-10-06)

Status: **accepted production runtime; tracked documentation refresh**

- Protected/deployed SHA: `4c6ae50091fb568b491eacbffa0fec53a444092d`.
- Post-merge protected CI: PASS.
- Exact-source changed-image builds: backend PASS; image derivative PASS; frontend PASS.
- Sharp runtime: 0.35.5; libvips 8.18.7.
- Public/User/API smoke: 200; Owner Access boundary: 302.
- Production unhealthy/restarting: 0/0.
- Anti-stall runtime source hash matches protected source; heartbeat 10s, stale-running 180s, provider hard timeout 150s.
- Maintenance admission reopened at generation 50.
- A compose command timed out after creating exact new containers. Effects were reconciled before continuation; created exact containers were started explicitly with no blind replay.
- Rollback tags and the old rollback server remain preserved.
- NS-12 original observation window remains unchanged.
- Runtime project_hub journal contains `postcutover-release4c6-fr25-20261006`; generated STATE/PROJECT-REPORT remain runtime-generated only.

Primary evidence is retained in the migration evidence store as `RELEASE-4C6AE500-PRODUCTION-ROLLOUT-20261006.json` (SHA-256 `594df70df61ae0faf0d908fdc38b498741fb32f2fb13e8421bb706e2225bd214`).

Remaining release gates: NS-14A disconnect/reconnect fault matrix and completion of the original NS-12 72-hour observation window.
