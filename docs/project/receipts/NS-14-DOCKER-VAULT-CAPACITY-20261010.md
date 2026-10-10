# NS-14 — Docker/containerd encrypted-vault space coverage (2026-10-10)

**Status: SOURCE-ONLY / NOT DEPLOYED / NO PRODUCTION STORAGE CLEANUP.**

## Evidence
Owner's read-only new-host `nc-ph-4354` checks showed 36 running production containers, 35 healthy and Cloudflared running without a healthcheck; `df -h` reported root `/dev/md2` with about 3.0 TB available (9% used) but a separate shared Docker+containerd encrypted vault `/dev/mapper/aionex-container-runtime-vault` of 63 GB with about 23 GB free (62% used). `docker system df` reported 26.54 GB of nominally reclaimable images and 2.466 GB build cache, neither a promise of actual freed blocks nor authorization to delete rollback images.

## Root cause and source-only change
`scripts/operations/host-capacity-guard.py` only polled `/`. A nearly-full Docker image runtime vault could therefore evade the existing owner disk warning. Add `docker_disk_pct` based on `/var/lib/docker` filesystem usage alongside the existing root `disk_pct`, with existing 70% warning, 85% critical and debounced recovery semantics. Extend the protected backend `runtime_host_alert.py` allowlist to accept this metric; add offline regression tests for separate mount measurement, escalation and recovery. No Docker socket is added to application containers, no new credentials or cloud services are used.

## Boundaries
- This does not expand or clean the runtime vault. Do NOT run `docker system prune -a`, drop volumes, detach LUKS or replace production image tags without independently verified rollback and disposal authorization.
- Source inclusion is not live activation. Verify exact protected SHA, then only apply this guarded change during a reviewed new-host release, with Owner durable notification acceptance and original containers still healthy.
- FR-09 5,000-user full mixed acceptance remains **NOT RUN**. Its separate 40 GiB free-space staging criterion, FR-08 dependency and isolated no-provider lab remain unchanged; the production vault's observed ~23 GB available **does not pass** that criterion.
- Historical old-host thresholds were based on 12 logical CPUs and must be calibrated to new-host characteristics as a separate task; do not assert 5,000 simultaneous GPU workloads from session/read tests.
