# 36N — Production server capacity guard

Date: 2026-09-07

## Purpose

The Owner requires an automatic early signal when the current Namecheap production host approaches the measured launch capacity boundary, so a server upgrade can be ordered before sustained overload becomes an outage.

## Measured host baseline and acceptance basis

The current production host is a 12-logical-CPU Intel Xeon E-2236 system with about 62 GiB usable RAM, RAID1 SSD storage and a 1-Gbps WAN link. The bounded 2026-09-07 capacity exercise proved zero HTTP errors through 400 concurrent readiness requests, while latency entered the pressure region above 200 concurrency. A dedicated 200-concurrency sample completed 4,000/4,000 requests successfully at approximately 62.1% host CPU busy. The isolated Phase36H control-plane/backplane acceptance admitted and connected 1,000/1,000 synthetic participants with zero rejections, p95 admission about 65.83 ms and Redis-delivery p95 about 12.30 ms. This does not claim 1,000 simultaneous live audio/video streams.

## Guard design

A new root-side `scripts/operations/host-capacity-guard.py` is run by the existing `aionex-runtime-watch.timer` every minute. It does not expose the Docker socket to application containers and reads only host kernel/filesystem/network counters. It sends sanitized threshold transitions through the existing `app.services.runtime_host_alert` bridge so notifications use the same durable Owner communication pipeline.

Thresholds:

- CPU: warning 70%, critical 85%.
- Memory: warning 75%, critical 85%.
- Root filesystem: warning 70%, critical 85%.
- 1-minute load normalized by logical CPU count: warning 75%, critical 100%.
- WAN utilization per full-duplex direction: warning 65%, critical 80% of detected link speed.
- Swap: warning 20%, critical 50%.

A warning requires three consecutive minute samples. A critical transition requires two consecutive critical samples. Recovery requires three consecutive safe samples. Persisted transition state deduplicates repeated notifications while pressure remains active. A warning explicitly says that a server upgrade should be prepared; a critical event says that server capacity must be upgraded or load reduced immediately. Recovery is also notified.

The Owner notification bridge uses the project's existing channel policy: durable in-app delivery plus Telegram when the single protected Owner endpoint is ready, otherwise Email fallback. Capacity messages carry only metric name, percentage, threshold and transition metadata; no host credential or secret enters the notification payload.

## Pre-deploy acceptance

Pure transition regression: PASS for warning debounce, critical escalation, dedupe and recovery. Live host baseline sample before deployment: CPU 15.49%, memory 11.15%, root disk 37.70%, normalized load 22.09%, swap 0.43%, network near idle; every metric classified `healthy`. The existing runtime-watch timer is active.

Production activation remains gated on protected PR/CI/merge. After merge the systemd service definition must be installed/reloaded, the timer must remain active, a normal live sample must persist all metrics as healthy, and a bounded synthetic notification acceptance must prove the Owner delivery path without generating host load.

## Production acceptance addendum

- PR #587 merged as `2955d6c`; all protected checks passed, including Production Docker Build.
- Host timer is enabled/active and the capacity state file is being written under `/var/lib/aionex-runtime-watch/`.
- Acceptance warning and recovery both produced durable In-app and Telegram deliveries with no delivery error code.
- A follow-up hardening change initializes Redis in the host-alert CLI so immediate realtime In-app publication is available in addition to durable delivery.

## Final Production Acceptance — 2026-09-07

The Capacity Guard is now merged, deployed, and verified on Production.

- PR #587 introduced the host-side Capacity Guard and Owner capacity alert contract.
- PR #588 added Redis lifecycle ownership for the host alert CLI.
- PR #589 fixed the final realtime lifecycle boundary by starting/stopping `realtime_event_runtime` around host alert emission.
- Final runtime merge commit: `b76aa5e895fe223f60da2f880f81a04baea9ea65`.
- `aionex-runtime-watch.timer`: enabled and active.
- Last `aionex-runtime-watch.service`: `Result=success`, `ExecMainStatus=0`.
- Final observer image: `sha256:0db1fb8fc0b641da50f5c3570ed4ec829b339a204d98c9a223a3a5da2cf64449`.
- `operations-observer`: running, healthy, restart count 0.

### Live Owner notification acceptance

A synthetic capacity warning and recovery were emitted through the exact Production host-alert bridge without applying real load to the server.

Warning transition `910003`:
- event: `operations.host.capacity_warning`
- In-app: `delivered`
- Telegram: `delivered`
- Telegram provider receipt: present
- delivery error code: none
- realtime publish warning: none

Recovery transition `910004`:
- event: `operations.host.capacity_recovered`
- In-app: `delivered`
- Telegram: `delivered`
- Telegram provider receipt: present
- delivery error code: none
- realtime publish warning: none

### Post-acceptance host state

- Production containers running: 35
- unhealthy: 0
- aggregate restart count: 0
- `/ready`: HTTP 200
- CPU: healthy (34.26% at final sampled cycle)
- memory: healthy (11.38%)
- disk: healthy (38.36%)
- normalized load: healthy (29.54%)
- network: healthy (0.0% at final sampled cycle)
- swap: healthy (0.42%)

**Certification:** the Production server now has an active, durable, debounced Capacity Guard that issues explicit Owner upgrade recommendations before sustained resource pressure reaches the measured critical boundary, escalates critical pressure, and emits recovery notifications after the host returns to the safe range.
