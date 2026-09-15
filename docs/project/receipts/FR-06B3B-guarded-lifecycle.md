# FR-06B3B — guarded lifecycle and final-delta executor

Status: source-only executor and isolated rehearsal passed; production unchanged.

## Decision

FR-06B3B adds the bounded executor that FR-06B3A deliberately omitted. It does not turn a preflight receipt into an unconditional production authorization. Every production operation remains bound to the exact `/opt/AIOS` checkout, exact `origin/main` merge SHA, the fixed production environment and Docker socket, a private root-owned state directory, fresh FR-06B3A evidence, a current owner-approved window, an expiring plan, an exclusive lock, an unrepeatable reservation, an exact plan-derived confirmation, and a second production-only confirmation.

A successful cutover stops at `candidate_started_admission_closed`. The executor does not open application admission. That later decision remains outside this program and requires live acceptance.

Production preflight is strictly ordered before mutation. It requires a measured legacy p95 baseline, but rejects candidate p95 and final-delta/drain/stop claims as premature. Those results are produced and retained only after the one-time plan is consumed and before any separate decision to open admission.

## Retained source

- `scripts/security/fr06b_guarded_lifecycle.py` implements `plan-cutover`, `apply-cutover`, `guarded-start`, and `rollback`.
- The plan binds SHA-256 digests for the evidence, runtime snapshot, and B3B contract; it expires after at most 900 seconds and is consumed once before the first mutable step.
- In production, B3B also invokes the B3A inspector itself at planning, apply, immediately before candidate start, and before every guarded-start attempt. It rechecks active LUKS2 mappers, ext4 and mount options, all subpaths, mapper-backed Docker volumes, zero candidate consumers, and both Compose contracts instead of trusting a supplied JSON snapshot alone.
- Production paths, environment file, Docker sockets, service/root matrix, legacy volume names, and candidate mapper-backed paths are constrained by reviewed contracts. Paths that escape, overlap, or resolve through a final symlink are rejected.
- The executor resolves every live container ID for the 20 protected runtime definitions, including scaled services, and requires the topology to be identical when the plan is applied. It never targets unrelated services.
- After exact scoped stops, a `/proc` descriptor scan blocks any remaining writable host process across both legacy and candidate roots. The 11 retained legacy roots are then self-bind-mounted read-only with `nodev,nosuid` before the final copy, eliminating the stopped-writer-to-seal race.
- Final delta uses fixed, shell-free rsync arguments and the FR-06B1 no-symlink/no-hardlink/no-special-file manifest logic. All 11 roots must satisfy source-before = source-after = candidate while the source seals remain intact. Full filename-level manifests are retained only in private mode-0600 state; the result exposes counts, byte totals, and aggregate hashes.
- Candidate initializers run first, then all 11 sealed-source and post-initializer candidate manifests must still match before any runtime service may start. Only the previously active runtime services are recreated, at the exact prior scale, with both reviewed overlays, `restart: no`, no dependency start, and no image pull.
- An initializer-only or other pre-runtime failure restores the exact legacy runtime scale without copying candidate-only metadata back. Any failure after a candidate runtime start attempt first stops candidate consumers, then performs an exact reverse delta before restoring legacy. Blind base-Compose reversion after possible runtime writes is forbidden.
- `guarded-start` permits at most three attempts and reruns admission before each. Because `restart: no` keeps services stopped but transient bind seals disappear across a host reboot, missing or partial seals are rebuilt only under the exclusive lock after both legacy and candidate roots prove quiescent; the exact receipt-bound seal layout must then be restored and every legacy aggregate manifest must equal the cutover baseline before any candidate starts. Exhaustion leaves all candidates stopped with admission closed.
- Explicit rollback requires a successful tamper-evident cutover receipt retained in the private state directory, a fresh closed-admission preflight on the currently reviewed main, the identical root layout, stopped candidate consumers, quiescent legacy and candidate roots, an exact reverse delta, and another single-use confirmation. It safely tolerates reboot-lost seals, removes any surviving seals before copying, and never opens admission. A compatible later main commit does not make an older cutover receipt unusable merely because its commit changed.

## Isolated result

The retained receipt at `docs/project/receipts/FR-06B3B-isolated-guarded-lifecycle.json` was produced entirely below a disposable `/var/tmp` sandbox. It used real read-only bind mounts and a file-backed 20-service runtime model; it did not use the production Docker daemon for any lifecycle action.

The rehearsal proved:

- successful 11-root final delta and the closed-admission terminal state;
- preservation of all 20 guarded definitions and a three-instance scaled service;
- real read-only legacy seals and later clean unsealing;
- one-time replay rejection, topology-drift rejection, exclusive-lock rejection, and path-escape rejection before mutation;
- reboot-style legacy-seal loss followed by guarded, lock-held resealing, exact baseline validation, and restart while admission remained closed;
- rejection before candidate launch when an isolated legacy root was modified while reboot seals were absent;
- manual reverse-delta rollback including a new candidate-side write;
- automatic reverse-delta rollback after a candidate health failure;
- pre-candidate rollback without an unjustified reverse copy;
- removal of every temporary bind mount, private state tree, and sandbox;
- unchanged production container identity.

## Boundary

This source batch does not authorize production execution. It does not apply either production overlay, stop or restart a production service, write a production volume, create or unlock a production vault, handle key material, change a production mount, restart Docker, reboot the host, change Cloudflare, or open application admission.

It does not close FR-06B or FR-06. FR-06B4 must first retain protected PR and post-merge-main checks for this source, a fresh encrypted R2 restore, external independent active/recovery-key custody, separate off-host LUKS2 headers, an independent owner-visible alert, production boot and Docker-restart evidence, and a newly approved maintenance window. Even after an authorized cutover, opening admission requires separate live health, permission, backup, build, and p95 acceptance with regression no greater than 15 percent.
