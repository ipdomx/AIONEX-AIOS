# NS-15 — Post-rollout canonical reconciliation (2026-10-06)

Status: **runtime rollout accepted; tracked continuity refresh candidate**

## Accepted production state

- Protected-main/application release: `960dab80fe8ec27b1e8bf59425b766e03f9b9783`.
- Protected post-merge Final Validation: PASS.
- Security Baseline / CodeQL / Browser E2E / Container Security: PASS.
- New production source checkout: exact protected main, clean.
- Affected runtime images: exact `release-960dab80` tags with source/image hash verification for the conversation worker.
- Public site / user portal / API health / API ready: HTTP 200.
- Owner portal: HTTP 302 through Cloudflare Access boundary.
- Production unhealthy containers: 0.
- Production restarting containers: 0.
- Cloudflare / LiveKit / TURN: running.
- Maintenance admission: reopened at generation 48 after guarded rollout acceptance.
- Rollback images and old rollback server: retained.
- Original NS-12 observation start remains `2026-10-05T16:43:26Z`; application rollout did not reset it.
- Dependabot open alerts: 0. Four earlier source-manifest Trivy Docker-module findings remain documented as evidence-backed not-used dismissals; no absolute-security claim.

## Conversation anti-stall runtime proof

- Heartbeat: 10 seconds.
- Stale running fail-closed threshold: 180 seconds.
- Provider hard timeout: 150 seconds.
- Running conversation worker file hash matches protected source.
- Conversation API routes are present and fail closed without authentication.
- Broader disconnect/reconnect fault-matrix acceptance remains open under NS-14A; this receipt does not claim it is already complete.

## Runtime ledger reconciliation

The prior sanitized append-only `docs/project/runtime/events.jsonl` journal was restored from the retained management/rollback host to the new production host with matching SHA-256 before new material events were recorded. Generated `STATE.json` and `PROJECT-REPORT.md` are rendered/validated only with `scripts/project_hub.py` and are not hand-edited.

Primary rollout evidence is retained outside Git under the migration evidence store and referenced by the runtime checkpoint. No credentials, host IPs, SSH key material, raw environment files, or customer content are recorded here.

## Remaining release gates

1. Continue NS-12 observation until the original 72-hour gate.
2. Complete the remaining NS-14A transport/reconnect fault matrix without duplicate provider execution or charge.
3. Keep monitoring/backup/restore/security evidence clean.
4. Do not retire the old server before the observation gate and explicit Owner approval.
5. Do not set RELEASED_VERIFIED until FR-25's complete exit contract is satisfied.
