# FR-06C5D9A — Production Realtime maintenance-admission closeout

This receipt reconciles the tracked FR-06 map with the accepted live D9A rollout. PR #747 merged as `7be95f99a18bfc6d0b3e894cf8ae8992962f0383` after 12/12 candidate checks, all five post-merge `main` workflows passed, and the server source was synchronized cleanly.

Before the Production migration, a fresh 22,332,307-byte PostgreSQL dump at Alembic `20260920_0062` was restored independently. Maintenance admission was closed from schema 7 generation 13 to generation 14 under operation `a9106826-f376-4f9d-a24e-3d185f2901ad`, Backend was stopped immediately, and the other authority consumers were stopped after the measured active-work set was clear. Preserved notification rows that accumulated as `queued` while closed did not create provider attempts and were not treated as active drain blockers.

The database was upgraded by an exact-main one-shot container with `--no-deps` from `0062` to `0063`. The migration preserved the closed operation and produced schema 8 generation 15 with the eighth scope `realtime_media_requests`. Eleven affected application containers were recreated on exact-main images; all 25 non-target container identities remained unchanged, including PostgreSQL, Redis, Nginx, Frontend, Portal, Cloudflare, LiveKit, TURN, Egress, ZAP and Ollama.

While authority remained closed, all eight scopes returned `admitted=false`; a live Realtime admission probe returned `HostMaintenanceClosed` and performed no LiveKit/provider I/O. A fresh 22,336,749-byte post-migration dump was independently restored at `0063/schema8/generation15/closed`. Authority was then reopened to generation 16 and all eight scopes returned `admitted=true`.

Final acceptance was 36 running containers, 35 healthy, zero unhealthy, zero critical-log matches on the eleven affected services, internal Backend health/ready and Frontend/Portal HTTP 200, and public/user/owner/API-ready boundaries 200/200/302/200. The existing ZAP credential exclusivity remained intact.

This closeout proves the Production request/resume admission boundary for Realtime media. It does **not** prove durable LiveKit room/participant/token/Egress/recording ownership, token expiry, provider completion, session/Egress drain, remaining producer coverage, or full-host closure. Those remain FR-06 work.
