# FR25 — Pinned httpx security-builder Go module download reliability (2026-10-14)

**AIONEX AIOS only**. Prepared on NEW `nc-ph-4354` against protected `main` `f56a4a6f67a475754f50b04bc4853c3d43480f1d`.

## Real failure

The first post-merge push of PR926 showed **Production Docker Build RED** in the security tools image's `httpx-builder` stage at `go mod download all`. Original job [115849131213](https://github.com/ipdomx/AIONEX-AIOS/actions/runs/38563179126/job/115849131213) returned code 1 after about 174 seconds. It emitted `AIONEX_BUILD_FAILURE` with a retained-log digest and 246 bytes, but the failing Docker layer was discarded and no runner artifact was uploaded, so **the underlying Go downloader message cannot be verified from the captured job output**. Do not guess a particular DNS error or hash mismatch. All 12/12 original PR926 head checks were green before merge.

## Narrow fail-closed correction

Modify only `web-dashboard/backend/scripts/build_httpx.py` for the locked `go mod download all` step:
- At most **three attempts** on exactly the same pinned `go.mod`, pinned `go.sum`, immutable upstream tarball SHA256, pinned Go toolchain and GOFLAGS `-mod=readonly`; each attempt gets a distinct log and hash.
- Bounded per-attempt timeout **240 seconds**, with only **2- and 5-second** retry delays; no change to actual source, dependency versions, lockfiles, runner tests, compiler, final binary expected SHA256, severity or image scan.
- Immediate **fatal stop** on checksum/integrity failure, invalid module version, unknown revision, incorrect Go version or required `go.mod` edit; never bypass upstream checksum evidence.
- Persistent download errors still emit the original `AIONEX_BUILD_FAILURE` and fail Docker build. On success after a retry, emit an explicit recovered-attempt count and retain all attempt hashes and return codes in `go-module-download-attempts.json`. A recovered network operation is **not an accepted product or security release**.

## Evidence

- Original `tests/test_fr06_security_httpx.py` plus synthetic focused retry test suite **42/42 PASS**, proving transient failure recovery on the same arguments, hard stop on checksum failures and version mismatch, preservation of module locks, bounded three-attempt red outcome, and timeout recovery.
- Syntax and `git diff --check` PASS. No production container, user data, old host, DNS, Cloudflare, API keys or providers touched.
- Full original exact-HEAD protected GitHub CI (especially the actual security-tools Docker builder, SBOM and vulnerability gate) is mandatory. This source-level unit success cannot prove the live remote download will succeed.

**Release remains** `FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED`. FR06 host-state boot/custody, FR08/FR24 independent customer restoration, real 5,000-user workload, NS12 continuous stability and old-host encrypted disk archival are independent release blockers.
