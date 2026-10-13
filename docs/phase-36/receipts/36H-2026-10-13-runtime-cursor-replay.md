# Phase 36H â production-runtime cursor replay repair (2026-10-13)

Status: **SOURCE PR OPEN / ISOLATED RUNTIME SUBGATE PASS / NOT DEPLOYED**

## Change

PR [#923](https://github.com/ipdomx/AIONEX-AIOS/pull/923) wires resumable delivery into the actual FastAPI WebSocket runtime. Events with a bounded `event_id` are retained in tenant-hashed Redis lists, deduplicated and published atomically, and replayed after `after_event_id` on reconnect. Live events arriving during replay are queued and overlap is delivered once. Legacy events without `event_id` remain live-only.

## Independent verification on NEW

The source tree based on protected main `b39be73b745ddfa5cf529c83a2a8588c3ff7d930` ran in the isolated encrypted lab on `nc-ph-4354`:

- actual PostgreSQL 16, Redis and FastAPI WebSocket route: **25/25 passed**;
- a terminal event published while the authenticated client was disconnected replayed after reconnect;
- duplicate terminal publication retained and delivered one event;
- an unknown cursor replayed no history and the authenticated socket remained usable;
- tenant retention keys were hashed and isolated;
- focused, revocation and transport/scale tests: **41 passed, 2 skipped**;
- lab containers after cleanup: **0**;
- production continuity: **36 running / 35 healthy / 0 bad**, identities unchanged and no restart.

Root-only evidence remains on NEW:

- operational proof SHA256: `148078fd38c7e8af0ee90d40cf115831b18876c994adfcfaab843b2fac31c22b`;
- orchestration receipt SHA256: `746695eeef2b81791625dd1b82c5cb0e5be9f3fc804d199391ccbc4340f74ceb`;
- continuation checkpoint SHA256: `f317c713717fd06976b6d880cfe91fafc40cf77d01b87d569ab4187c30b3076a`.

## Acceptance boundary

This receipt covers a source fix and isolated operational subgate only. Protected-branch CI, merge and post-merge verification are still required. The application was not deployed and production services were not restarted. Full NS14A, FR08E, FR08 and FR09 remain open; the actual 5,000-user workload was not run and must not start before full independent FR08 admission.
