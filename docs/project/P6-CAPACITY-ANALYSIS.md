# P6 gate 6.1: capacity analysis and tuning (FR-09 / NS-13)

Status: source analysis plus tooling only. Nothing here was measured on production. The 5000-user run happens in the pre-launch window (owner decision 2026-11-06), using `scripts/capacity/p6_mixed_load.py`.

## What the history shows

| Date | Run | Result |
|---|---|---|
| 2026-10-05 | 1000-user full mixed harness | FAIL: 21,896 errors, authenticated-read P95 2,759 ms |
| 2026-10-05 | 4-shard 1000-user read-only | PASS, reads only (P95 17 ms) |
| 2026-10-05 | NS-13 2500/5000 read-only staged envelope | sampled reads only, P95 about 21 ms |
| 2026-10-24 | 5000 synthetic accounts | passed, but "not proof of 5000 simultaneous authenticated HTTP connections"; P95 above 500 ms, HOLD |

Read-only traffic is fast. Latency collapses when logins, writes and many concurrent authenticated sessions mix. Five causes in the source explain that pattern. They are ordered by expected impact.

## Findings

### F1. Every visitor shares one rate-limit bucket (launch blocker)
`web-dashboard/docker/nginx.conf` keys `api_per_ip` (20 r/s, burst 40), `auth_per_ip` (5 r/min, burst 8) and `connections_per_ip` (20) on `$binary_remote_addr`. Behind the Cloudflare tunnel, that address is the cloudflared container for every client (receipt `FR09-CLOUDFLARED-TRUSTED-REALIP-20261024.md`). The effects:
- The whole internet shares 5 logins/min and 20 API requests/s. Rejections are nginx **503**, so they show up as a 5xx storm, and the request queue inflates P95.
- This also explains Phase 0.1 ("nginx blocks `/auth/refresh` 112 times in 48 h"). Those were not individual looping clients. They were all users hitting one shared bucket.
- **Action (owner, before 6.1 and permanently for launch):** activate the existing `docker-compose.fr09-trusted-realip.yml` overlay after `scripts/security/fr09_cloudflared_realip_admission.py --apply`. Do NOT change `limit_req_status` to 429: `vip-frontend/src/lib/auth-refresh-gate.ts` treats a 429 on refresh as terminal and logs the user out.
- For the test itself, one generator IP still hits per-IP limits. The time-boxed `docker-compose.p6-loadtest-window.yml` handles this. Its entrypoint is `nginx-p6-loadtest-entrypoint.sh` and its exemption file comes from `scripts/capacity/p6_loadtest_exemption.py`. The overlay exempts only up to 4 public /32 or /128 addresses, has an expiry of at most 8 h, requires real-IP, and refuses to start Nginx once the exemption expires. CI (`nginx-docker-dns-validation.yml`) runs `nginx -t` on the rendered config and checks that an expired file is refused.

### F2. Argon2 ran on the asyncio event loop (fixed in code)
`AuthService.authenticate` called `pwd_context.verify_and_update` synchronously inside `async def`. With Argon2id at m=64 MiB, t=3, p=4, that is tens to hundreds of ms of CPU per login. During that time the uvicorn worker serves **no other request**. With 4 workers, a login burst during the ramp stalls every endpoint, which matches "reads fast alone, slow when mixed".
- **Fix (this PR):** `app.core.auth.hash_password / verify_password / verify_and_update_password` run on a per-process bounded `ThreadPoolExecutor` (`PASSWORD_HASH_THREADS`, default 2, range 1-16). argon2-cffi releases the GIL, so the loop keeps serving. The bound also caps transient Argon2 memory at threads x 64 MiB. All request-path call sites were switched: login, register, free registration, password reset, password change and MFA disable. Test: `web-dashboard/backend/tests/test_p6_password_hash_offload.py`.
- Residual: the login transaction still holds its DB connection during the hash (the `select User` opens it). That is acceptable at about 21 logins/s in the last ramp stage. Revisit it if the DB pool wait shows up in the receipt.

### F3. Too few API processes for the CPU they are allowed
Production runs `WORKERS` = 4 (config default) on `cpus: 4.0`, with a DB pool of 4 x (12 + 2) = 56 out of a budget of 60. Python request handling is CPU bound per process. The existing FR-09 overlays (`workers8-pool56`, `backend-cpu`) were never combined with a measured run.
- **Tuning (opt-in, `docker-compose.p6-capacity-tuning.yml`):** `WORKERS=8` on `cpus: 8.0` and `mem_limit: 6g`. DB pool 8 x (6 + 1) = 56 <= budget 60, so Postgres `max_connections=100` keeps headroom for the workers. `PASSWORD_HASH_THREADS=1` per process gives 8 parallel hashes. The 6.1 run must measure this exact file, and if it passes, this is the file that ships.

### F4. Redis pool too small for 5000 sockets
The backend uses `BlockingConnectionPool(max_connections=REDIS_POOL_SIZE=18, timeout=5 s)`. `PROJECT_EXECUTION_ADMISSION_CONCURRENCY=14` can hold 14 of those 18 connections. That leaves 4 per process for access-token revocation checks on every authenticated request, the realtime hub, and FR-09 presence heartbeats. Under load the remaining requests wait up to 5 s, which lands directly in P95.
- **Tuning:** `REDIS_POOL_SIZE=48` per process (8 x 48 = 384 clients, well under Redis `maxclients` 10000). The config validator still requires admission <= pool - 2.

### F5. No upstream keep-alive from nginx to uvicorn (documented, not changed)
`proxy_pass http://$backend_upstream` (a variable, chosen so Docker DNS re-resolves after a container is recreated, as validated by `nginx-docker-dns-validation.yml`) means there is no `upstream` block and no `keepalive` pool. nginx also sends `Connection: close`, so every request opens a new TCP connection to uvicorn. Inside the Docker bridge this costs well under 1 ms, so it is not a P95 driver, and nginx `worker_connections 2048 x auto` is ample. If 6.1 shows connect overhead, the fix is an `upstream backend { zone ...; server backend:8000 resolve; keepalive 64; }` block (nginx >= 1.27.3), with `proxy_set_header Connection ""`. That change must keep the DNS re-resolution test passing. It is not applied now.

### Not a factor
- Uvicorn defaults (`backlog` 2048, no `limit_concurrency`) are fine. The app is served by `uvicorn.run(workers=N)`, not gunicorn, so there is no gunicorn worker class to tune.
- nginx `cpus: 1.0`: plain-HTTP proxying (TLS ends at Cloudflare) is cheap. The tuning overlay gives it 2.0 for headroom during the run.

## How 6.1 is judged
`p6_mixed_load.py` receipt (`aionex.p6.mixed-load.v1`):
- Steady-window P95 of all non-AI requests < 500 ms (FR-09's stricter ordinary-read P95 <= 500 ms still applies through `fr09_evidence_gate.py`).
- Error rate < 1 % over the whole run. Governed AI denials count separately and are never hidden.
- No 5xx storm, meaning no 10 s bucket with >= max(20, 1 %) 5xx.
- 5000 VUs signed in for the full steady window (default 900 s).
- AI requests capped at 0.2/s and 4 in flight by default (AIONEX AI capacity), with `confirm_external_processing=false`, so the load test never triggers paid external processing.

FR-09 FULL_MIXED acceptance additionally needs the HMAC-signed server presence samples (`AIOS_FR09_AUTHENTICATED_PRESENCE_*` + `fr09_presence_capture`). Every VU holds a realtime socket, so presence is measured by the server, not claimed by the generator. It also needs DB accounting, and both are judged by `scripts/capacity/fr09_evidence_gate.py`.

## Policy note
FR-09F (2026-10-10) required the 5000-user test to run in an isolated lab. The 2026-11-06 owner decision moves all live verification into the pre-launch window against the real API. The harness supports both: `--allow-lab-target` covers the FR-09 LUKS lab. Running against `api.vip-e.net` is an explicit owner choice, recorded in the runbook. Its safeguards are synthetic `.invalid` accounts only, no owner notifications, a capped AI rate, hard stops, and a pre-launch window with no customers.

## 6.1 runs on production (2026-11-07/08)
Each run was a mixed authenticated load against `api.vip-e.net`, with synthetic accounts, from this host. Each run surfaced the next real limit, and every fix below is live and in `docker-compose.p6-capacity-tuning.yml`.

| Run | Peak users | Result | Limit found → fix |
|---|---|---|---|
| 1 | ~100 | 30 s responses | `sync_catalog` locked every plan row and walked every tenant on each billing read (#1042) |
| 2 | ~1900 | P95 2 s | backend 8-core quota; 403 on plan-gated ads counted as errors (#1044) |
| 3 | ~1700 | 5xx | nginx `EMFILE`: soft limit 1024 per worker, 64 workers from `auto` → 4 workers, `worker_rlimit_nofile 65536` |
| 4 | ~1500 | P95 < 320 ms, 51 x 502 | nginx → backend ephemeral ports (`EADDRNOTAVAIL`) → port range + `tcp_tw_reuse` |
| 5 | ~3600 | 217k requests, 0 errors, P95 1.6 s in ramp | Argon2 login burst + CPU |
| 1000-user steady | 1000 | **PASS**: P95 118 ms, 0 errors | none |
| 7 | ~3600 | 296k requests, 0 errors, no CPU throttling | per-process event loop (16 workers) |
| 8 | ~3000 | P50 100 ms, P95 2 s | DB pool 1+1 per process with 32 workers |
| 9 | ~2450 | 196k requests, 0.03% errors, P95 0.4–0.9 s | QueuePool exhaustion (5+2 per process) after Postgres raised to 300 connections / 2 GiB |

**Open (next run):** find which request path holds DB sessions long enough to exhaust a 7-connection pool at ~100 sockets per process, and fix that before raising pools further. PgBouncer in transaction mode is the fallback if the hold is inherent.
