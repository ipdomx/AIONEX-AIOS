# 36N — Production capacity test — 2026-09-07

Scope: bounded, non-destructive capacity validation on the existing Namecheap production host. No paid AI/provider request was generated, no live media stream was synthesized, and no production queue residue was left behind.

## Host baseline

- CPU: Intel Xeon E-2236, 6 physical cores / 12 logical CPUs, 3.40 GHz base / up to 4.80 GHz.
- RAM: 62 GiB usable; ~6.9–7.1 GiB used during the test; ~55 GiB available.
- Storage: 2 x 894.3 GiB Samsung SSD devices in md RAID1; array `[UU]`; root ext4 ~878 GiB with ~502 GiB available.
- Network: production `wan0` negotiated at 1000 Mbps.
- Production services: 35 running containers.
- Baseline load average near 2.7 on 12 logical CPUs; I/O wait effectively zero in bounded sampling.

## HTTP/control-plane concurrency

Local production readiness traffic was increased in bounded stages through the real local production listener. Every request returned HTTP 200.

| concurrency | requests | errors | throughput | p50 | p95 | p99 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 2,000 | 0 | 977.5 rps | 21.78 ms | 37.09 ms | 187.00 ms |
| 50 | 3,000 | 0 | 873.6 rps | 53.50 ms | 74.02 ms | 208.45 ms |
| 100 | 4,000 | 0 | 939.9 rps | 102.66 ms | 136.25 ms | 156.29 ms |
| 200 | 5,000 | 0 | 779.6 rps | 227.38 ms | 349.85 ms | 475.84 ms |
| 300 | 6,000 | 0 | 684.0 rps | 332.94 ms | 854.39 ms | 1,505.75 ms |
| 400 | 8,000 | 0 | 790.1 rps | 428.32 ms | 826.39 ms | 983.01 ms |

A separate 200-concurrency / 4,000-request CPU probe completed 4,000/4,000 successfully with aggregate host CPU busy ~62.1%; Backend remained healthy and `/ready=200` immediately afterward.

Interpretation: 100 concurrent control-plane requests remain comfortably inside the low-latency region. 200 concurrent remains successful with substantial CPU headroom but higher p95. 300–400 produces no failures but crosses into a latency region unsuitable as the normal launch target. The bounded test intentionally stopped rather than driving production toward failure.

## Realtime PostgreSQL/Redis control-plane scale

The existing Phase36H isolated synthetic runtime acceptance was executed against the production PostgreSQL/Redis control plane with 1,000 synthetic participants, 10 tenants and 4 logical hubs. It does not activate or claim 1,000 simultaneous live audio/video streams.

- requested/admitted/consumed/connected: 1,000 / 1,000 / 1,000 / 1,000
- admission rejections: 0
- p95 admission latency: 65.83 ms
- p95 Redis delivery latency: 12.30 ms
- Redis delivered events: 1,000
- cross-tenant leaks: 0
- duplicate deliveries: 0
- failed deliveries: 0
- node-loss simulation: 250 affected presences, 250 reaped, 250 recovered
- stale Redis subscribers: 0
- gate result: PASS

## Post-test integrity

- 35 production containers remained running.
- Backend remained `healthy`, restart count 0.
- `/ready=200` immediately after the test.
- Active Project/Studio/3D/Image/Video/Speech/Transcript/Dubbing/Music/Song queues all returned zero.
- RAM remained ~7.1 GiB used with ~55 GiB available.

## Capacity decision

The current server does not require a RAM or storage upgrade for initial commercial launch. RAM and SSD/RAID capacity have large headroom. CPU is the first local resource expected to become limiting as user concurrency and CPU-heavy workers grow; the 1-Gbps public interface is the independent future limit for high-volume realtime audio/video.

Conservative launch operating target on this host: up to ~100 simultaneously active application/control-plane users without changing capacity settings, with bursts around 200 supported by the measured host. This is not a claim that every one of those users can simultaneously run a heavy project build or live video session. Heavy Project Execution remains governed by the deployed 4 workers x capacity 3 = 12 simultaneous heavy execution slots, with queueing/admission providing safe overflow.

Upgrade trigger: sustained production CPU >70–75%, HTTP/API p95 materially above the product SLO during normal traffic, persistent Project Worker saturation/queue age, or public-network saturation. RAM alone is not an upgrade trigger on the measured system.
