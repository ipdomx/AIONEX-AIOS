# FR09 read latency: optimized ASGI, live Owner policy and API sharding

2026-10-25; isolated encrypted Docker lab. **The launch is not accepted.**

The production main ae18cb8 was used as the source baseline. Two changes
were tested independently: a pure ASGI security-header middleware without
BaseHTTPMiddleware task scheduling, and a single combined live PostgreSQL
read of Owner policy layers plus user-owned thread rows after fresh user,
role and organization authorization. No authority is cached; suspended layers
continue to deny. There is a regression test preserving the 1,000-thread
maximum when fewer than three policy rows exist.

Real PostgreSQL 16 disposable integration test suite: **70 tests passed**.
The synthetic database and JWT credentials were destroyed after testing.

## Four vs eight API containers; fixed total eight workers and eight CPU cores

Control: four containers x two workers. Candidate: eight containers x one
worker. The PostgreSQL connection ceiling remains 56 and the same synthetic
250-user / 750-project / 750-task set and Nginx transport are used.
Each stage sent 750 authenticated HTTP requests through user identity,
project list and conversation list. ABBA total = 3,000 HTTP-200 responses.

| Route (P95 ms) | A1: 4x2 | B1: 8x1 | B2: 8x1 | A2: 4x2 |
|---|---:|---:|---:|---:|
| identity | 468.57 | 365.33 | 341.63 | 410.37 |
| projects | 304.11 | 288.94 | 313.98 | 322.65 |
| conversations | 575.52 | 240.87 | 269.32 | 627.17 |

**The 8x1 candidate passed the 500 ms limit on all three reads in both
250-user candidate stages.** This is *not* acceptance of the full 5,000
authenticated multi-tenant 15-minute mixed load.

## 500-user ramp

500 real synthetic authenticated users and 1,500 synthetic projects / tasks
were seeded in the disposable PostgreSQL lab. One valid stage of 1,500 HTTP
reads was run per configuration. Both resource-expanded configurations failed
the full all-route 500 ms P95 target:

| 500-user configuration | Identity P95 | Projects P95 | Conversations P95 |
|---|---:|---:|---:|
| 500_users_8x2_workers16_cpu16 | 472.58 ms | 655.22 ms | 635.29 ms |
| 500_users_16x1_workers16_cpu16 | 535.23 ms | 602.46 ms | 261.91 ms |

Other validated negative experiments (CPU doubling without other changes,
database connection ceiling changes and fused identity/Owner policy joins)
are explicitly excluded from any production rollout.

## Required before final launch

No final GO: demonstrate full 5,000 authenticated active users distributed
over distinct tenant organizations, 15,000 projects, 15,000 conversations,
15,000 durable completed jobs and **separately** 15,000 generated model
inferences with accurate accounting, <=500 ms ordinary read P95,
<=1,000 ms enqueue P95, <=0.5% unexpected errors, no tenant leakage,
15-minute real steady state and 72 natural hours of post-deploy stability.

No old stability sample was reclassified and no production container was
restarted by the isolated tests. See the retained JSON file and each
original evidence SHA-256 for precise measurements.

## Verification and rollout constraint

Source verification on the sealed lab with PostgreSQL 16:

- 70 real synthetic-governance/security integration tests passed, including
  global/plan/user Owner suspension, tenant isolation, conversation locking,
  1,000-thread inbox limit, and passthrough streaming security headers.
- Ruff static checks passed for the two touched modules and new tests.
- Independent SHA-256 receipts for every synthetic A/B profile are retained in
  FR09-20261025-READ-PERFORMANCE-250-500-BOUNDARY.json.
- The isolated lab used network=none and never read production customer
  records; original production image/ID/start-time identities did not change.

Only source changes have been prepared for review. Any GitHub merge requires
passing the protected branch CI gates. Do not automatically deploy a source
merge. A later production rollout would need a new release generation and a
fresh 72-hour timer; the existing G6 series must not be credited to it.

This is NOT a GO for 5,000 mixed active users or 15,000 real LLM
inferences. The 500-user ramp failed all-route P95 under 500 ms.
