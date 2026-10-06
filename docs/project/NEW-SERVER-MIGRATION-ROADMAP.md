# AIONEX AIOS — New Production Server Migration Roadmap

## Current authoritative state — 2026-10-06

Status: CUTOVER_COMPLETE_NEW_SERVER_AUTHORITATIVE_NS12_OBSERVATION_ACTIVE_FR23_MERGED_ANTI_STALL_PR872_PROTECTED_CI

- The new Debian 12 production server is the authoritative public runtime.
- The old production server is retained intact as the rollback anchor and must not be retired before the original NS-12 observation gate and explicit Owner approval.
- Protected GitHub `main` is currently `fa19d69412e2a28f266a0934ca20597215b8672c`, which includes the merged FR-23 security dependency closure from PR #870.
- The currently deployed application release remains `46eb80c8b7474d26f1cc9a2c8718aabd4d842391` until a newer protected-main rollout is explicitly accepted.
- Canonical FR-09 1,000-user acceptance is PASS on the new server; the staged authenticated-read growth envelope through 5,000 sessions is recorded as a synthetic capacity envelope, not a claim of 5,000 simultaneous heavy AI/GPU generations.
- NS-12 observation started at `2026-10-05T16:43:26Z`; the earliest 72-hour completion is `2026-10-08T16:43:26Z`. Application updates do not reset this original window.
- FR-07F conversation anti-stall/reconnect protection is implemented as PR #872 at exact head `cd2fd3077e61af60ad79fff83b6186af65a6bca8`; local focused acceptance is PASS and protected exact-head CI is still authoritative before merge/deploy.
- NS-15 canonical reconciliation is active in PR #871. Until that PR merges, this branch is the reviewed documentation candidate while the append-only runtime checkpoint remains the immediate execution ledger.

### Current continuation transport

The approved continuation path is **MCP2 management entry -> approved SSH administration channel with strict host-key verification -> new production server -> clean exact-SHA checkout/worktree**. The tracked map intentionally does not contain the new host IP, SSH private-key path/material, credentials, or raw environment secrets.

## Historical migration baseline — 2026-10-04

The block below is the original pre-migration baseline and must not be treated as the current runtime state after cutover.

Status at that time: NEW_SERVER_PROVISIONED_PROVIDER_HARDWARE_VERIFIED_AWAITING_INDEPENDENT_HOST_AUDIT

### Live authority and continuity rule

Before any continuation, operator or assistant action must reconcile all of the following rather than trusting a screenshot or stale paragraph:

1. protected GitHub main and the exact candidate/head commit SHA;
2. the latest retained migration/runtime checkpoint and evidence;
3. the actual new-host source SHA, running image identities, database/schema state and health;
4. current protected CI for the exact head being considered;
5. rollback state on the old server.

If these disagree, the discrepancy is recorded as documentation drift and live/GitHub evidence wins until canonical reconciliation. A stale map must never trigger a blind pull, reset, deletion, deployment, replay or provider action.

The new dedicated server has been purchased and access details have been received. The provider control panel shows Debian 12 x86_64. Provider technical support has confirmed all of the following:

- All 4 x 1.92 TB NVMe drives are detected correctly.
- The drives are configured as RAID 10.
- The RAID array is healthy, fully synchronized, and has no degraded disks.
- The server has the full 128 GB RAM.
- Both AMD EPYC 7313 CPUs are detected correctly.

No application data has been uploaded to the new server. Migration has not started. The existing production server remains the source of truth and must remain online and unchanged until the cutover, observation, rollback, and retirement gates below are all satisfied.

Expected new-server profile:
- Dual AMD EPYC 7313, 2 x 16 physical cores, 32 physical cores total.
- 128 GB RAM.
- 4 x 1.92 TB NVMe in RAID 10, approximately 3.84 TB usable before filesystem overhead.
- 1 Gbps unmetered network subject to provider network-protection/fair-use policy.
- Debian 12 x86_64.
- User-Responsible management.
- No cPanel, Webuzo, Softaculous, or WHMCS.
- Full root and out-of-band IPMI/recovery access expected.

Never store passwords, SSH private keys, IPMI credentials, recovery keys, provider secrets, raw environment files, or customer data in this roadmap, Git, receipts, or chat logs.

## Migration invariants

1. The old production server remains authoritative until explicit cutover acceptance.
2. No destructive change, wipe, cancellation, or cleanup of old production before rollback-retirement approval.
3. Provider confirmation is not enough by itself; an independent read-only host audit must pass before the first data upload.
4. No blind copying of secrets. Secrets move only through approved secure handling and are never committed.
5. RAID is redundancy, not backup. A separate encrypted backup and tested restore path is mandatory.
6. Public traffic is not switched until the new server passes isolated application acceptance.
7. The new server has a different public IP. Every direct-IP dependency, allowlist, callback, webhook, monitoring target, and external integration must be inventoried before cutover.
8. Prefer the existing Cloudflare Tunnel architecture so public hostnames are not tightly coupled to the server IP.
9. The old and new servers run in parallel during migration and observation.
10. Every phase ends with a documented PASS, HOLD, or ROLLBACK decision.
11. No paid-provider fanout or real customer data is used in load tests unless separately approved.
12. Deferred scope remains deferred: XR, unconnected/secondary providers, payments/store-app activation, and other explicitly deferred items are not silently reactivated by the migration.

## NS-00 — Independent pre-migration host audit

Run before uploading any application data.

Verify from the new server itself:
- Debian 12 release and kernel.
- CPU model, sockets, cores, threads, NUMA topology.
- Total RAM, available RAM, memory topology/ECC visibility where exposed.
- All four NVMe devices, model/firmware/health, without publishing sensitive hardware identifiers.
- RAID 10 membership and health.
- Array fully synchronized, no rebuild, no degraded member.
- Actual usable filesystem capacity consistent with RAID 10.
- Partition table and boot layout.
- Boot redundancy and recovery path.
- Filesystem type, mount options, free space, and inode capacity.
- Network interfaces, link state, negotiated speed, gateway, DNS resolution, and time synchronization.
- Root access works.
- IPMI/out-of-band console access works independently of SSH.
- No unexpected hosting panel or preinstalled stack is present.
- No unexplained public listeners.

Exit: independent OS/hardware/RAID/network baseline PASS. If anything differs from the order or provider confirmation, stop before upload and have the provider correct it.

## NS-01 — Host security baseline

Before installing the application:
- Apply Debian 12 security updates using a controlled maintenance step.
- Record the kernel and package baseline.
- Set final hostname, timezone, NTP/chrony/systemd-timesyncd and verify synchronized time.
- Establish approved SSH key access.
- Establish least-privilege admin/sudo path and emergency root recovery.
- Harden SSH and disable weak authentication/algorithms according to project policy.
- Configure firewall/nftables with deny-by-default inbound policy.
- Expose only explicitly required management and application paths.
- Configure fail2ban or equivalent brute-force protection.
- Configure unattended security updates consistent with maintenance policy.
- Configure journald/logrotate retention and disk-growth controls.
- Verify no accidental public DB, Redis, Docker API, metrics, or admin listeners.
- Keep IPMI credentials outside the project repository and application environment.
- Confirm the provider network and reverse DNS requirements, if any.

Exit: hardened host with a proven independent recovery path.

## NS-02 — Storage and filesystem operating model

Before copying production state:
- Confirm RAID 10 health monitoring.
- Enable periodic RAID health checks/scrubs where appropriate.
- Confirm NVMe SMART/health monitoring.
- Choose the final filesystem and mount layout before bulk data transfer.
- Define separate locations for application source, Docker data, database volumes, uploads/assets, logs, build/cache data, and migration staging.
- Preserve large free-space headroom; normal production should not be planned near the old server's 95% usage.
- Target operational disk warnings before 70%, escalation at 80%, urgent remediation before 85%.
- Define cleanup rules for build caches, stale worktrees, temporary artifacts, old images, and logs.
- Keep backup copies off the same server/RAID.
- Confirm backup target capacity and encryption.

Exit: storage layout documented, health monitoring available, and independent backup destination ready.

## NS-03 — Base runtime installation

Install only required supported components:
- Docker Engine.
- Docker Compose v2.
- Git and deployment utilities.
- Required monitoring/storage/network tools.
- Cloudflared package and service files prepared but not used for production cutover yet.
- Host Node/Python tooling only when genuinely required; prefer project containers for reproducibility.
- Required systemd units only from reviewed project source.
- No cPanel or unrelated hosting stack.
- Record all installed versions.

Exit: clean reproducible host runtime with no production traffic.

## NS-04 — Source and configuration preparation

- Fetch the canonical ipdomx/AIONEX-AIOS repository from protected main.
- Use the approved new-server production root.
- Verify exact commit SHA and clean checkout.
- Do not copy a dirty old-server checkout as the source of truth.
- Validate Compose files and deployment manifests before startup.
- Prepare required directories, permissions, ownership, and file modes.
- Migrate configuration through secure secret handling.
- Never commit secrets or raw env files.
- Inventory all old-IP dependencies before changing them:
  - firewall allowlists,
  - provider callbacks,
  - webhooks,
  - monitoring targets,
  - outbound allowlists,
  - third-party dashboards,
  - backup endpoints,
  - SSH trust/known-host references where operationally relevant.
- Preserve all current deferrals and provider-live safeguards.

Exit: source/configuration ready with no public traffic and no paid-provider side effect.

## NS-05 — Pre-migration backup and rollback package

Before copying mutable production state:
- Create a fresh encrypted production backup using the accepted backup path.
- Create a consistent PostgreSQL backup/snapshot and verify integrity.
- Capture required persistent volumes, uploads, assets, and metadata.
- Capture service topology and deployment manifests without exposing secrets.
- Record:
  - source commit SHA,
  - container image identities/digests where available,
  - database schema/migration level,
  - application release/version,
  - backup timestamp,
  - RPO reference point.
- Verify the backup can be read.
- Perform an isolated restore test before relying on it.
- Establish rollback owner and rollback trigger criteria.

Exit: independently restorable pre-migration package PASS.

## NS-06 — Initial bulk migration while old production stays live

- Transfer immutable and large data first.
- Use integrity-preserving copy methods and checksums/manifests.
- Copy application uploads/assets and persistent storage.
- Restore a database copy to the new server in isolated mode.
- Do not blindly copy ephemeral caches.
- Restore Redis persistent state only if required by the application contract.
- Bring up PostgreSQL, Redis, application containers, and supporting services on the new server without public production traffic.
- Keep old production accepting normal traffic.

Exit: isolated complete replica available for testing.

## NS-07 — Isolated application acceptance

Validate the new server before any public cutover:
- Expected containers start successfully.
- Intentionally drained services remain intentionally drained.
- No running container is unhealthy.
- Backend health/readiness endpoints pass.
- PostgreSQL connectivity, schema, migrations, row/data integrity, indexes, and extensions are correct.
- Redis connectivity and queue/session semantics are correct.
- Nginx public/private origin layout is correct.
- Public portal, user portal, and Owner portal routes work.
- Authentication and authorization work.
- Owner controls, suspension, revocation, policy limits, and audit trails work.
- Multiple projects and multiple conversations work.
- Save/resume and isolation work.
- Upload/download and asset isolation work.
- WebSocket/event-stream behavior works.
- Six-language, RTL, dark mode, mobile, Safari, and accessibility checks run where applicable.
- Browser E2E, security baseline, source validation, and final validation suites pass.
- Provider connectors remain synthetic/fail-closed unless a separately approved real-provider acceptance is required.
- Resource/provider credit alerts and monitoring contracts work.

Exit: isolated new-server application acceptance PASS with no unexplained regression.

## NS-08 — Cloudflare and network cutover preparation

- Inventory all current DNS records, Tunnel routes, Access policies, callbacks, webhooks, monitoring endpoints, and direct-IP dependencies.
- Preserve current Cloudflare policy; migration is not permission to redesign Access or DNS.
- Prepare the new server as a reviewed Cloudflare Tunnel connector/origin.
- Keep the old connector/origin available for rollback.
- Verify the user portal, public site, and Owner portal private/public routing boundaries.
- Update direct-IP allowlists or callbacks deliberately, one by one, with evidence.
- Reduce DNS TTL only where a direct DNS switch is genuinely needed.
- Test the traffic-switch and rollback method before the maintenance window.

Exit: reversible traffic-switch plan proven.

## NS-09 — Rehearsal and final-delta plan

- Perform a complete rehearsal restore from accepted backup.
- Measure restore duration.
- Reconcile DB integrity, file counts, hashes/manifests, and persistent-volume completeness.
- Define the final maintenance/write-drain window.
- Define which queues/jobs must drain or stop accepting new work.
- Confirm no ambiguous in-flight provider jobs.
- Define final database snapshot and file-delta synchronization procedure.
- Confirm rollback can be executed without relying on the new server.

Exit: signed-off cutover checklist and proven rollback.

## NS-10 — Production cutover

Sequence:
1. Enter the controlled maintenance/write-drain window.
2. Gate new mutable work on the old server using accepted controls.
3. Allow in-flight work and queues to reach the defined safe state.
4. Take final DB backup/snapshot.
5. Perform final delta sync of persistent files/assets.
6. Restore/apply final delta on the new server.
7. Re-run migrations, DB integrity, readiness, permissions, and filesystem checks.
8. Start the new production stack.
9. Verify internal health before public traffic.
10. Activate the new Cloudflare Tunnel connector/origin or other preapproved traffic switch.
11. Run real-public-hostname smoke tests.
12. Verify authentication, Owner portal, user portal, projects, conversations, uploads, queues, DB, Redis, and critical APIs.
13. Monitor closely.
14. Keep the old server intact and ready for rollback.

Exit: production traffic successfully served by the new server while rollback remains available.

## NS-11 — Immediate rollback criteria and procedure

Rollback immediately for any material:
- database inconsistency or missing data,
- authentication/authorization regression,
- persistent 5xx/availability failure,
- broken Cloudflare routing or Access,
- queue duplication/loss or unsafe replay,
- corrupted upload/download,
- billing/entitlement inconsistency,
- critical security regression,
- critical monitoring/backup failure that makes continued operation unsafe.

Rollback sequence:
- Stop new writes on the new server.
- Route traffic back to the old server using the preplanned switch.
- Confirm old-server health before reopening writes.
- Preserve new-server evidence; do not wipe it.
- Reconcile data written during the attempted cutover before any second attempt.

## NS-12 — Post-cutover observation

Keep both servers for at least 72 hours, and longer if operational evidence requires it.

Monitor:
- HTTP/API error rate and latency.
- Authentication and authorization failures.
- PostgreSQL health, connections, locks, replication/backup state where relevant.
- Redis memory, latency, persistence, and queue behavior.
- Queue depth and wait time.
- Container health/restarts.
- CPU/load and scheduler pressure.
- RAM/swap/OOM events.
- RAID/NVMe health.
- Disk space, filesystem growth, IOPS and latency.
- Network throughput and 1 Gbps ceiling.
- Cloudflare Tunnel health.
- Scheduled jobs and monitoring.
- Backup success, age, and restoreability.
- Security/update/audit findings.

Exit: stable observation window with no unresolved critical issue.

## NS-13 — Capacity acceptance and 5,000-user growth readiness

The new hardware is intended to provide significant headroom, but 5,000 users does not mean 5,000 simultaneous heavy AI/GPU generations on one host.

Required:
- Re-run the canonical 1,000 authenticated-user / multiple-project / multiple-conversation acceptance on the new production-equivalent configuration.
- Characterize safe staged synthetic concurrency, as appropriate, across 500, 1,000, 2,500, and up to 5,000 sessions/projects without uncontrolled paid-provider fanout.
- Measure p50/p95/p99 latency.
- Measure request rate, error rate, queue depth/wait, CPU, RAM, swap, DB connections/locks, Redis, disk IOPS/latency, and network throughput.
- Preserve tenant isolation, zero lost jobs, and zero duplicate terminal executions.
- Abort escalation on correctness loss, rising 5xx, DB/queue saturation, swap thrash, unsafe provider fanout, RAID/storage pressure, or network saturation.
- Record a safe operating envelope rather than claiming unlimited capacity.
- Treat the 1 Gbps network as a possible future bottleneck.
- Define horizontal scale-out triggers:
  - additional application/worker nodes,
  - dedicated database node,
  - dedicated Redis/queue node,
  - external object storage/CDN for large assets,
  - specialized media/AI workers.
- Scale horizontally before a single-host bottleneck becomes a production incident.

Exit: measured capacity report with clear limits and scale-out triggers.

## NS-14 — Monitoring and ongoing operations

Required alerts:
- RAID degraded/rebuild.
- NVMe SMART/health.
- Disk and inode pressure.
- CPU/load.
- RAM/swap/OOM.
- Container unhealthy/restart loops.
- PostgreSQL availability/resource pressure.
- Redis availability/resource pressure.
- Queue depth/wait/failures.
- Public endpoints and Cloudflare Tunnel.
- Backup success/age/restoreability.
- Provider credit/usage alerts.
- Security updates/audit findings.

Maintain cleanup for:
- stale worktrees,
- build caches,
- obsolete images,
- old temporary migration files,
- logs and diagnostics,
while preserving evidence required by project policy.

## NS-14A — Client response and streaming resilience

This is a release-scope requirement prompted by the observed class of UI failure where a long response can stop with a generic “streaming interrupted / waiting” state. The external ChatGPT client failure is not evidence that AIOS itself has the same bug, but the analogous failure mode is now explicitly in AIOS scope and must be tested before final release closure.

Required behavior for every AIOS long-lived response, stream, live progress feed, or equivalent asynchronous delivery path:
- Never silently hang forever. Use bounded idle/overall timeouts plus heartbeat/progress semantics where a long-lived transport is used.
- Preserve the accepted request/job identity independently of the client transport.
- A network drop, app background/foreground transition, proxy timeout, server restart, or client reconnect must not create a duplicate billable provider request or duplicate terminal execution.
- If the transport is resumable, reconnect from an acknowledged cursor/sequence/event id with bounded exponential backoff and jitter.
- If the upstream/provider stream cannot be resumed, the client must fall back to durable job/status retrieval rather than pretending the partial stream completed.
- Duplicate/replayed chunks or terminal events must be idempotently de-duplicated.
- UI states must distinguish connecting, streaming/running, reconnecting, recovered, completed, cancelled and failed; a generic indefinite spinner is not acceptable.
- Partial content/progress that is safe to retain should remain visible after reconnect.
- Authentication/session expiry during reconnect must fail closed and present a recoverable user action without losing the underlying durable job when policy permits.

Acceptance must cover at least: mid-stream TCP drop, Cloudflare/proxy interruption, client app background/foreground, network change, repeated reconnect, duplicate events, server/container restart, auth refresh/expiry, terminal-event loss, and fallback polling/status recovery.

Status: IMPLEMENTED_CANDIDATE_PR872_PROTECTED_CI_IN_PROGRESS. Source and focused local acceptance exist at exact PR #872 head `cd2fd3077e61af60ad79fff83b6186af65a6bca8`; this is not yet a production-acceptance claim and protected exact-head CI plus post-merge rollout smoke remain required.

## NS-15 — Canonical documentation reconciliation

After stable cutover:

### Exact-SHA new-server operating discipline

The accepted operating path is explicit and immutable-SHA based:

1. MCP2 may land on the retained management/old host; do not infer from the MCP name that the process is executing directly on the new host.
2. Reach the new host only through the already-approved SSH migration/administration channel with strict host-key verification; never place host IPs, private-key paths/material, credentials or raw host secrets in tracked docs.
3. Resolve the exact protected-main or reviewed PR head SHA from GitHub before mutation.
4. On the new host, fetch the required ref and verify the exact SHA. Do not use a blind `git pull` as the release decision.
5. Build/test from a clean detached worktree or clean checkout bound to that immutable SHA. Dirty source is never release authority.
6. Protected CI evidence is valid only for the exact head SHA it tested. A newer commit requires fresh exact-head acceptance.
7. Before rollout, preserve rollback source/image identities and revalidate maintenance/admission authority.
8. After rollout, verify runtime source/content hashes or image identities, database/schema expectations, public/authenticated health and relevant feature smoke against the accepted SHA.
9. Keep the old server and rollback artifacts intact until the observation/retirement gates and explicit Owner approval are satisfied.

This is the continuity method to use if a conversation is interrupted: recover the last accepted SHA and evidence first, then continue from the new host without replaying already-performed effects.

### Update ledger and map reconciliation policy

Every material project transition must be retained, including unsuccessful work. The minimum record is: UTC time, phase/batch, exact source/candidate SHA, target environment/host role, action, outcome, evidence reference/hash where available, whether production was mutated, and the explicit next action.

Allowed operational outcomes are at least: IN_PROGRESS, PASS, FAIL, BLOCKED/HOLD, PENDING_RETRY, ROLLBACK and COMPLETE. Failed or superseded attempts are evidence and are not overwritten to make the history look clean.

The append-only runtime journal/checkpoint is the immediate execution ledger. The canonical PLAN/roadmap is the durable reviewed summary and is reconciled at material checkpoints; transient minute-by-minute CI polling does not require a Git commit for every poll. Generated STATE.json and PROJECT-REPORT.md are updated through `scripts/project_hub.py`, never hand-edited.

Before starting a new continuation, read the canonical map, latest checkpoint/journal, GitHub protected state and live new-host evidence. If any “done / failed / still required” state is absent or contradictory, record the drift before further mutation.

- Update PLAN and canonical project state through scripts/project_hub.py.
- Never hand-edit generated STATE.json or PROJECT-REPORT.md.
- Record the new production hardware profile, Debian 12 baseline, source SHA, images, DB schema, migration/cutover timestamp, and acceptance evidence.
- Update recovery, backup, monitoring, and rollback runbooks.
- Confirm the old public IP is no longer required by any DNS record, allowlist, callback, webhook, monitoring target, or provider integration.
- Never store credentials in tracked documentation.

Exit: source, production, documentation, monitoring, and recovery evidence agree.

## NS-16 — Old-server retirement

Only after all prior gates and explicit Owner approval:
- Take final archival backup of old production.
- Independently verify new-server backup/restore.
- Confirm no user traffic, scheduled job, provider callback, monitoring target, or Cloudflare route still depends on the old server.
- Rotate/revoke old-server-only credentials and SSH trust as appropriate.
- Remove the old Cloudflare Tunnel connector only after new-connector stability is proven.
- Preserve required audit/history evidence.
- Contact provider Billing to cancel the old server only after explicit Owner approval.
- Never cancel early merely to save cost.

## Migration complete definition

Migration is complete only when all are true:
- Independent new-host audit PASS.
- Security/storage/runtime baseline PASS.
- Source/configuration/data migration verified.
- New server serves public production traffic.
- Required production acceptance PASS.
- Canonical 1,000-user capacity acceptance PASS on the new server.
- 5,000-user growth envelope and horizontal scaling triggers are documented honestly.
- Backup/restore/recovery and monitoring PASS.
- Old-server rollback observation window completes successfully.
- Client response/stream delivery resilience acceptance PASS, including reconnect/fallback without duplicate execution or provider charge.
- Canonical project documentation is reconciled.
- Owner explicitly approves retirement of the old server.

Until then the status remains MIGRATION_IN_PROGRESS_NOT_COMPLETE.
