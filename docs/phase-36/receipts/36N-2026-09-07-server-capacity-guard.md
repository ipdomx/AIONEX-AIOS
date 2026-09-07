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
