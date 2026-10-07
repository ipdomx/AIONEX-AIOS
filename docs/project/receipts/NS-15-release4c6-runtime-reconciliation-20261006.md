# NS-15 — release 4c6 runtime reconciliation (2026-10-06)

Status: **accepted backend runtime plus accepted VIP shared-hosting security release; tracked documentation refresh**

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

## VIP security follow-up — 2026-10-07

- PR #878 exact head `9be98e7eda77532bbf7979955f0a22f3cef46dd0` merged as protected main `1fedff22300c1abb699439f32409bbb10ccb7ce7`.
- Exact-head and post-merge CI: PASS.
- Dependabot open alerts after reindex: 0.
- VIP Sharp: 0.35.5.
- `vip-frontend verify:static`: PASS.
- Existing shared-hosting deployment route was used; no DNS or Cloudflare Tunnel change.
- Pre-deploy remote backup: `/home2/ipdom3m7/.aionex-deploy-backups/20261007T101040Z-ai-vip-before-sharp0355`.
- Package-owned SHA-256 parity after publication: `362/362`.
- All six locale roots, login, projects, API health and API ready: HTTP 200.
- Backend containers were not redeployed for this VIP-only change.
- Evidence SHA-256: `4c849305f1a114e3872b558d8f7147fdb238b8872a5eeee426a9335bce489e41`.

Current split authority is therefore explicit: protected main and VIP shared-hosting runtime are `1fedff22...`; backend/new-server application runtime remains accepted at `4c6ae500...`. NS-12 keeps its original start and is not reset by either release.
