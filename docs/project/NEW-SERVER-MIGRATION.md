# AIONEX AIOS — New Production Server Migration Master Plan

## 0. Current authoritative status
- Migration state: NEW_SERVER_PROVISIONED_AWAITING_HARDWARE_VERIFICATION.
- New dedicated server has been purchased and access details have been received.
- Control panel reports Debian 12 x86_64.
- Intended hardware/service profile:
  - Dual AMD EPYC 7313, 2 x 16 physical cores, 32 physical cores total.
  - 128 GB DDR4/ECC-class RAM as ordered.
  - 4 x 1.92 TB NVMe.
  - RAID 10 expected by provider default, approximately 3.84 TB usable before filesystem overhead.
  - 1 Gbps unmetered public network subject to provider fair-use/network-protection policy.
  - User-Responsible management, full-root/IPMI-class access expected.
  - No cPanel, Webuzo, Softaculous or WHMCS.
- No application data has been uploaded to the new server.
- No migration has started.
- The existing production server must remain unchanged and online.
- Support confirmation is still required for: all four NVMe devices detected, RAID10 healthy/fully synchronized, full 128 GB RAM detected, and both EPYC CPUs detected correctly.
- Never store passwords, private SSH keys, IPMI credentials, recovery keys, provider secrets, raw env files, or customer data in this plan or Git.

## 1. Non-negotiable migration invariants
1. Old production remains the source of truth until explicit cutover acceptance.
2. No destructive action on the old server before rollback retirement approval.
3. No data upload to the new server before hardware, RAID and OS baseline passes.
4. No blind copying of secrets; migrate through approved secure channels and preserve least privilege.
5. RAID is redundancy, not backup. A separate encrypted backup/restore path must exist and be tested.
6. No paid/provider/media workload is used for migration testing unless separately approved; prefer synthetic/no-network tests.
7. Cloudflare, DNS and IP dependencies are inventoried before cutover because the new physical server has a different public IP.
8. Do not cancel the old server until post-cutover observation, rollback expiry, backup verification and Owner approval are complete.
9. Every phase ends with evidence and an explicit PASS, HOLD or ROLLBACK decision.

## 2. Phase NS-00 — Provider and hardware verification before data
Required before any migration data:
- Confirm Debian 12 x86_64 from the OS itself, not only the provider UI.
- Confirm CPU model, count, topology and both sockets.
- Confirm total and available RAM and ECC visibility where exposed.
- Enumerate all four NVMe devices and model, firmware and health without exposing sensitive identifiers in public docs.
- Confirm RAID10 membership, state, sync or rebuild state, no degraded member and expected usable capacity.
- Confirm partition table, filesystem type, free space, mount layout and boot redundancy.
- Confirm network interface and link, negotiated speed, gateway, DNS and time synchronization.
- Confirm root access and out-of-band IPMI or console recovery access.
- Confirm no unexpected control panel or preinstalled hosting stack.
Exit: hardware, OS, RAID and network baseline PASS. Otherwise HOLD and ask provider to correct before upload.

## 3. Phase NS-01 — New-host security baseline
Before application installation:
- Patch Debian 12 security updates and record kernel and package baseline.
- Set hostname, timezone and NTP; verify clock synchronization.
- Establish approved SSH key access, least-privilege admin and sudo path, and emergency root recovery strategy.
- Harden SSH with key-based authentication, sane root policy and no weak algorithms or password exposure.
- Configure firewall or nftables with deny-by-default inbound policy and only required management or service paths.
- Install and configure fail2ban or equivalent brute-force protection.
- Configure unattended security update policy consistent with maintenance windows.
- Configure journald and log rotation, audit retention and disk-growth limits.
- Verify no unintended public listeners.
- Preserve IPMI as independent emergency access; never expose IPMI credentials in project files.
Exit: security baseline PASS with remote recovery path proven.

## 4. Phase NS-02 — Storage, RAID and filesystem operating model
- Keep RAID10 healthy and establish periodic RAID scrub or check monitoring.
- Verify NVMe SMART or health reporting and alertability.
- Decide final filesystem and mount layout before copying production data; avoid later disruptive repartitioning.
- Reserve adequate headroom; do not plan persistent production above 70 to 75 percent disk usage.
- Define locations for application source, Docker data, database volumes, uploads and assets, logs, temporary build data and local staging.
- Keep encrypted backups off the same RAID and server; local copies are convenience only.
- Define log, build and worktree cleanup policy before launch.
Exit: storage layout documented, health checks working and independent backup target identified.

## 5. Phase NS-03 — Host software/runtime baseline
Install only required supported components:
- Docker Engine and Docker Compose v2 at project-approved versions.
- Git and deployment tooling.
- Required host utilities for health, storage, networking, backups and observability.
- Any required Node or Python tooling only when host-side execution is genuinely needed; prefer project containers for runtime consistency.
- Cloudflared package and service prepared but not cut over yet.
- No cPanel or hosting-panel stack.
- Reproduce only project-required systemd units and host policies from reviewed source; no stale legacy units.
Exit: clean host runtime with version inventory and no production traffic.

## 6. Phase NS-04 — Source and configuration preparation
- Fetch or clone canonical ipdomx/AIONEX-AIOS source into the approved new-server production path.
- Verify exact source commit and branch against protected main; never copy an arbitrary dirty checkout.
- Validate Compose and configuration syntax before startup.
- Prepare required directories, ownership and permissions.
- Migrate configuration through approved secure secret handling; never commit secrets.
- Review all IP-bound allowlists, callbacks, provider webhooks, monitoring targets and external integrations before changing them.
- Preserve deferred scope: XR, unconnected or secondary providers, payments or store apps, and other explicitly deferred items stay deferred unless separately authorized.
Exit: source and configuration prepared with no production traffic and no paid-provider effect.

## 7. Phase NS-05 — Backup and rollback package from old production
Before copying mutable production state:
- Create a fresh encrypted backup using the accepted backup path.
- Capture database backup or snapshot with integrity verification.
- Capture required persistent application volumes, assets, uploads and metadata.
- Capture configuration manifests and service topology without exposing secrets in logs.
- Record exact source commit, container image identities or digests where available, DB schema or migration level and deployment manifest.
- Verify backup readability and perform an isolated restore check before relying on it.
- Define RPO and RTO timestamps and rollback owner.
Exit: independently restorable pre-migration package PASS.

## 8. Phase NS-06 — Initial bulk migration while old server stays live
- Copy immutable and large data first using integrity-preserving transfer.
- Copy application assets, uploads and nonvolatile storage with checksums and manifests.
- Restore a copy of the database to the new server in isolated mode.
- Restore Redis AOF or RDB state only if required by application contract; do not blindly copy ephemeral caches.
- Bring up PostgreSQL, Redis and application containers on the new server in staging or isolation mode.
- Do not route public production traffic yet.
Exit: new server has a complete isolated replica suitable for testing.

## 9. Phase NS-07 — Pre-cutover application acceptance
Validate locally or through isolated routing:
- All expected containers start; intentionally drained services remain intentionally drained.
- No unhealthy running container.
- Backend health and readiness.
- PostgreSQL connectivity, schema version, migrations and data counts or integrity.
- Redis connectivity and queue or session semantics where applicable.
- Nginx origin layout and private or public origin bindings.
- Public portal, user portal and Owner portal routing.
- Authentication, authorization, Owner controls and revocation.
- Projects, multiple conversations, save or resume and file upload or download.
- WebSocket and event-stream behavior.
- Six-language, RTL, dark mode, mobile, Safari and accessibility acceptance where applicable.
- Browser E2E, security baseline and final validation suites.
- Provider connectors remain fail-closed or synthetic unless an approved real-provider acceptance is required.
- Credit and resource alerts and monitoring are functional.
Exit: isolated new-server acceptance PASS with no unexplained regression.

## 10. Phase NS-08 — Cloudflare and network cutover preparation
- Inventory every current DNS record, Cloudflare Tunnel route, Access policy, callback, webhook and allowlist that could depend on the old IP.
- Prefer the existing named Cloudflare Tunnel architecture so public hostnames do not depend directly on the new server IP.
- Add the new server as a reviewed Cloudflare Tunnel connector or origin only after local acceptance.
- Keep the old connector or origin available for rollback until final retirement.
- Do not change Cloudflare Access policy or unrelated DNS during migration.
- For any direct-IP dependency, update allowlists and webhooks deliberately and record each change.
- Reduce DNS TTL in advance only for records that genuinely require direct DNS cutover.
Exit: traffic-switch mechanism and rollback path proven.

## 11. Phase NS-09 — Rehearsal and final-delta plan
- Perform a full rehearsal restore on the new server from the accepted backup.
- Measure restore time and validate expected RPO and RTO.
- Reconcile file counts, checksums and DB integrity.
- Define final write-freeze or drain window.
- Define which queues and jobs must drain, stop accepting new work, or be replay-safe.
- Confirm no ambiguous in-flight provider jobs before final switch.
Exit: final cutover checklist signed off; rollback remains available.

## 12. Phase NS-10 — Production cutover
Sequence:
1. Enter the controlled maintenance or write-drain window.
2. Stop or gate new mutable work on the old server using accepted controls.
3. Wait for in-flight work and queues to reach the defined safe state.
4. Take final database backup or snapshot and final delta sync of persistent files.
5. Restore or apply final delta on the new server.
6. Re-run DB migration, readiness and integrity checks.
7. Start the new production stack.
8. Verify internal health before traffic.
9. Activate the new Cloudflare Tunnel connector or approved traffic switch.
10. Run immediate smoke tests through the real public hostnames.
11. Monitor errors, auth, DB, Redis, queues, uploads, projects or conversations and portals.
12. Keep the old server intact as rollback; do not delete or cancel it.
Exit: traffic successfully served by new server with rollback still live.

## 13. Phase NS-11 — Immediate rollback criteria and procedure
Rollback immediately on material:
- DB inconsistency or missing data.
- Authentication or authorization regression.
- Persistent 5xx or availability failure.
- Broken Cloudflare routing or Access.
- Queue duplication, loss or unsafe replay.
- Upload or download corruption.
- Critical provider-routing, billing or entitlement inconsistency.
Rollback procedure:
- Stop new writes on the new server.
- Route traffic back to old server through the preplanned switch.
- Restore old-server write acceptance only after confirming state.
- Preserve new-server evidence; do not delete it.
- Reconcile the final delta before another cutover attempt.
- No destructive cleanup during rollback.

## 14. Phase NS-12 — Post-cutover observation
Minimum observation before old-server retirement:
- Maintain both servers for at least 72 hours unless a longer period is operationally justified.
- Track HTTP and API error rate, latency, DB health and connections, Redis, queues, container health, CPU, RAM, disk I/O, network use, RAID or NVMe health and filesystem growth.
- Verify scheduled jobs, automations and external monitoring.
- Verify encrypted backup from the new server and perform a restore check.
- Verify Cloudflare Tunnel redundancy and no unexpected dependency on the old public IP.
- Review logs for security or permission regressions.
Exit: stable observation period with no unresolved critical issue.

## 15. Phase NS-13 — Capacity acceptance and 5,000-user growth readiness
Goal: establish headroom for a registered or active user base around 5,000 with multiple projects and conversations, without falsely claiming one server can execute 5,000 simultaneous heavy AI generations.
- Re-run the required 1,000-user project acceptance on the new server after production-equivalent configuration is proven.
- Characterize staged synthetic concurrency at 500, 1,000, 2,500 and 5,000 sessions or projects where safe, using no paid-provider fanout.
- Measure p50, p95 and p99 latency, CPU, RAM, DB connections and locks, Redis, queue depth and wait, disk IOPS and latency, network throughput and error rate.
- Abort load escalation on correctness loss, rising 5xx, DB or queue saturation, swap thrash, RAID or storage pressure, or unsafe provider fanout.
- Treat 5,000 as platform and user-capacity readiness, not proof of 5,000 simultaneous GPU or AI jobs.
- Scale horizontally before a single-host bottleneck: add app or worker nodes, dedicated DB, storage or queue services, or external object storage when sustained CPU, RAM, I/O, network or queue pressure reaches operational thresholds.
- Pay special attention to the 1 Gbps network ceiling; use CDN, object storage or worker separation when traffic profile justifies it.
Exit: measured capacity report with safe operating envelope and scale-out triggers.

## 16. Phase NS-14 — Monitoring and long-term operations on new server
Required alerts:
- RAID degraded or rebuild and NVMe health.
- Disk usage and inode pressure.
- CPU or load, RAM or swap, OOM.
- Docker or container unhealthy and restart loops.
- PostgreSQL and Redis availability and resource pressure.
- Queue depth, wait and failed jobs.
- Public endpoint and Tunnel health.
- Backup success, age and restoreability.
- Provider credit and usage alerts already required by project policy.
- Security update and audit findings.
Recommended disk thresholds: warn before 70 percent, escalate at 80 percent, urgent remediation before 85 percent; preserve enough free space for builds, backups and rollback.

## 17. Phase NS-15 — Documentation and source/production reconciliation
After stable cutover:
- Update canonical project state through scripts/project_hub.py; never hand-edit generated STATE or PROJECT-REPORT.
- Record new production hardware profile, OS, source commit, image manifests, DB schema level, migration evidence and cutover timestamp.
- Store public network identifiers only where operationally required; never store passwords, private keys or IPMI credentials.
- Update runbooks, recovery plan, backup inventory, monitoring endpoints and rollback records.
- Confirm old IP is no longer required by DNS, allowlists, callbacks, monitoring or provider configuration.
Exit: source, production, documentation and recovery evidence agree.

## 18. Phase NS-16 — Old-server retirement
Only after Owner approval and all prior exits:
- Take a final archival backup of old production.
- Verify the new-server backup and restore chain independently.
- Confirm no production traffic or scheduled job still reaches the old server.
- Revoke or rotate old server-only credentials, SSH host trust and monitoring identities as appropriate.
- Remove old Cloudflare Tunnel connector only after new connector stability is proven.
- Preserve required audit and history evidence.
- Contact provider Billing to cancel the old dedicated server only after explicit Owner approval.
- Never wipe or cancel early merely to save cost.

## 19. Definition of migration complete
Migration is complete only when:
- New hardware, RAID, OS and security baseline PASS.
- Source and persistent data are migrated and verified.
- Public traffic runs on the new server.
- Required production acceptance and 1,000-user capacity proof PASS.
- 5,000-user growth envelope is characterized without false simultaneous-AI claims.
- Backup, restore, recovery and monitoring PASS.
- Old server has completed the observation and rollback window.
- Canonical project docs are reconciled.
- Owner explicitly approves old-server retirement.

Until then, status remains MIGRATION_IN_PROGRESS_NOT_COMPLETE.
