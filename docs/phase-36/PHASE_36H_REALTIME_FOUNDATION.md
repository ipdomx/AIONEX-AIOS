# Phase 36H — Realtime communication, streaming & interactive media scale

Status: **IN PROGRESS — Part 1 foundation**

Started: 2026-08-24

## 1. Objective

Replace the current process-local realtime/WebSocket prototype with a provider-neutral production architecture that can scale horizontally, preserve tenant isolation, support WebRTC rooms/calls/screen share/recording, and produce deterministic load/failover evidence for the Phase 36 minimum 1000-concurrent-user profile.

Part 1 is deliberately source-only and dormant. It builds the distributed tenant-scoped transport contract and architecture evidence without activating an SFU, TURN service, recording service, opening firewall ports, restarting production, or making paid provider requests.

## 2. Actual starting state

- `app.core.ai_runtime.AIRealtimeHub` stores WebSocket membership in a Python dictionary inside one API process.
- `app.websocket.manager.ConnectionManager` is also process-local and singleton-shaped.
- The existing `/realtime/connect` route authenticates users and scopes them to `organization_id`, but event fanout does not cross API replicas.
- No production AIOS SFU/signaling cluster is currently implemented.
- No production TURN/STUN adapter is currently implemented for Phase 36H.
- No Phase 36H recording/egress adapter is currently implemented.
- No 1000-user realtime load/failover acceptance has been produced.

This is the exact gap Batch 36H must close; the current process-local hub cannot be accepted as the final architecture.

## 3. Technology refresh — 2026-08-24

Official upstream review:

- LiveKit server latest observed release: `v1.13.5` — https://github.com/livekit/livekit/releases
- LiveKit distributed architecture: Redis-backed multi-node routing and native connection draining — https://docs.livekit.io/transport/self-hosting/distributed/
- LiveKit production deployment/TURN guidance — https://docs.livekit.io/transport/self-hosting/deployment/
- LiveKit SFU architecture and horizontal scaling — https://docs.livekit.io/reference/internals/livekit-sfu/
- LiveKit adaptive stream/simulcast behavior — https://docs.livekit.io/transport/media/subscribe/
- LiveKit egress latest observed release: `v1.13.0` — https://github.com/livekit/egress/releases
- LiveKit self-hosted egress architecture — https://docs.livekit.io/transport/self-hosting/egress/
- Coturn latest observed release: `4.17.2` — https://github.com/coturn/coturn/releases
- Grafana k6 latest docs line observed: `v2.2.x`, release `v2.2.0` — https://grafana.com/docs/k6/latest/release-notes/
- OpenTelemetry Collector latest observed release: `v0.159.0` — https://github.com/open-telemetry/opentelemetry-collector-releases/releases

### Pin decision

LiveKit is the first SFU/signaling adapter candidate because its documented distributed mode uses Redis for room state/message routing, supports multi-node routing/draining, provides embedded TURN options, exposes Prometheus metrics, and has a separate egress service for recording. AIOS will not couple its durable room/admission policy to LiveKit-specific identifiers; the provider is behind an adapter boundary.

`v1.13.5` is **not yet approved as the production pin**. An open upstream high-room-churn goroutine/RSS growth report exists against that release. Part 1 therefore keeps the adapter version-selectable. A bounded lab soak and regression profile must decide whether the first production candidate is `v1.13.4`, `v1.13.5`, or a later fixed stable release. No production server is activated in Part 1.

Coturn `4.17.2` is retained as an external TURN fallback candidate. LiveKit embedded TURN remains a candidate as well. The final selection requires abuse-resistance, private-peer restrictions, rate-limit and failover tests.

## 4. Target architecture

`Client -> AIOS authenticated realtime admission -> durable room/session policy -> SFU adapter -> LiveKit cluster`

Supporting paths:

- Redis-backed tenant-scoped AIOS realtime event backplane for API replicas.
- Redis-backed LiveKit distributed mode for SFU node coordination.
- Explicit TURN/STUN adapter boundary; embedded LiveKit TURN and Coturn are independently selectable.
- Separate recording adapter to LiveKit Egress; recordings enter Creative Studio through governed artifact ingestion, never by bypassing storage/tenant policy.
- OpenTelemetry/Prometheus metrics for admission latency, active rooms/participants, reconnects, packet loss/jitter/RTT, bitrate, TURN usage, recording queue and failure state.
- k6 plus protocol-specific realtime load tooling for the 1000-user admission/WebSocket profile; media-node capacity is measured separately from API admission.

## 5. Security, privacy and abuse controls

- Tenant identity is mandatory on every admission, room, participant, event and recording boundary.
- Realtime event channels use a one-way tenant channel digest rather than exposing raw tenant IDs in Redis channel names.
- Room access credentials must be short-lived, least-privilege and never persisted in reports/logs.
- Recording is disabled unless explicit policy/consent state permits it.
- TURN must deny arbitrary relay abuse and unsafe private-network peer access.
- Admission quotas/backpressure are enforced before expensive SFU/recording allocation.
- No cross-tenant broadcast primitive is permitted in the production adapter.
- No paid provider call or external media activation is authorized by Part 1.

## 6. Part breakdown

### 36H.1 — Distributed realtime foundation

Build and test a dormant tenant-scoped Redis backplane and multi-node local fanout hub. Document architecture, technology review, risks and rollback. No production activation.

### 36H.2 — Durable rooms, presence and admission

Add durable room/session/participant policy state, idempotent room creation, presence leases, per-tenant quotas/backpressure, short-lived join grants and audit evidence.

### 36H.3 — SFU/signaling + TURN/STUN adapter

Implement the provider-neutral SFU contract and LiveKit candidate adapter; build disabled Compose/Kubernetes-compatible profiles; validate network boundaries and secrets without opening production media ports by default.

### 36H.4 — Calls, screen share and adaptive media quality

Wire 1:1/group calls, screen share, track policy, adaptive stream/simulcast/dynacast profiles and realtime quality metrics.

### 36H.5 — Recording and Creative Studio integration

Implement explicit-consent recording via Egress, bounded storage/retention, artifact provenance and Creative Studio ingestion.

### 36H.6 — Scale, failover, recovery and production gate

Run 1000-user admission/WebSocket load, concurrent realtime media scale profile, node loss/draining/recovery, TURN failure paths, recording failover and tenant-isolation tests. Only after evidence passes may 36H be raised to `scaled`/`production_ready`.

## 7. Part 1 acceptance

Part 1 passes only when:

1. a provider-neutral distributed realtime backplane contract exists;
2. tenant-scoped channel derivation does not expose raw tenant IDs;
3. two simulated API nodes subscribed to the same tenant receive the same event;
4. a different tenant receives no event;
5. first-client subscribe / last-client unsubscribe behavior is deterministic;
6. oversized/non-object events fail closed;
7. current production routes/services remain untouched and no provider request occurs;
8. project reports state both completed and not-completed work.

## 8. Rollback

Part 1 has no migration and no production activation. Rollback is a source revert. It must not require database restore, service restart, firewall rollback, TURN/SFU cleanup or provider cancellation.

## 9. Carried gates from 36G

36G provider/runtime gates remain truthful and independent. The absence of previously claimed `phase36g-final-closeout` artifacts was rechecked at the start of 36H and recorded in the project report. Phase 36H may progress on non-provider-gated work, but this does not convert 36G song production to `runtime_verified`.

## 10. Part 1 incident/change ledger

### 36H-P1-001 — Phase 36G closeout reporting discrepancy

- Date/time: 2026-08-24T09:03Z.
- Environment/component: production project reporting state on `/opt/AIOS`; Phase 36 registry and `.deployment-backups` reports.
- Visible symptom/user impact: a prior completion statement described final 36G closeout artifacts and a transition to 36H, but those named artifacts were absent and the authoritative registry/reports still identified 36G as `in_progress` behind the external live-song gate.
- Detection/reproduction: direct file existence checks for the three claimed closeout paths plus reads of `phase36-current-report/current.json`, `phase36-universal-provider-activation/current.json`, and `src/aios/phase36_program.py`.
- Root cause: the prior completion statement was not backed by corresponding server-side artifact/registry mutations. No deeper server mutation failure is asserted because no evidence proves one.
- Why existing checks did not prevent it: project tests validate repository state, but a conversational completion statement can still be wrong if server state is not re-read immediately before reporting.
- Fix: re-established server state as source of truth; preserved 36G capability maturity; introduced batch status `external_gate` for 36G and made 36H the sole `in_progress` batch; updated external project reports.
- Security/tenant review: no tenant data, credential, provider request or production route changed.
- Regression evidence: Phase 36 governance/capability tests now assert `36G=external_gate`, `36H=in_progress`, and `current_batch=36H`.
- Rollout/rollback: source/reporting only; revert the registry/report changes if evidence changes.
- Residual risk: 36G external live acceptance remains unresolved and must not be represented as runtime-verified.

### 36H-P1-002 — Initial local pytest invocation used the wrong interpreter/environment

- Date/time: 2026-08-24T09:10Z.
- Environment/component: development validation only.
- Visible symptom/user impact: first pytest invocation could not import SQLAlchemy; a subsequent invocation using the existing backend validation venv reached Settings validation without a test `SECRET_KEY`. Production was unaffected.
- Detection/reproduction: focused test command failed during collection before executing tests.
- Root cause: the generic tool interpreter did not contain backend dependencies; the backend venv requires an explicit non-production test secret for tests importing Settings.
- Why existing checks did not prevent it: the generic test runner is not bound to the project-specific validation venv.
- Fix: used `/tmp/aionex-p36c-backend-venv/bin/python`; tests that import Settings run with `ENVIRONMENT=test` and a disposable test-only `SECRET_KEY`.
- Security/tenant review: no production secret was read or reused; the test secret is synthetic and non-production.
- Regression evidence: focused Part 1 tests pass `5/5`; combined capability + Part 1 tests pass `6/6`; root Phase 36 governance tests pass `13/13`.
- Rollout/rollback: validation-only; no production change.
- Residual risk: full CI remains the authoritative environment-wide validation after PR creation.

### 36H-P1-003 — New batch status required a registry type-contract extension

- Date/time: 2026-08-24T09:09Z.
- Environment/component: source validation; `src/aios/phase36_program.py`.
- Visible symptom/user impact: broad Mypy validation rejected the new `external_gate` value because `BatchStatus` previously allowed only `complete`, `in_progress`, and `planned`. No production impact.
- Detection/reproduction: Mypy reported one Part 1 error at the 36G batch declaration. The same broad invocation also surfaced 32 type errors in unchanged legacy modules outside the Part 1 changed surface; those were not modified or represented as fixed.
- Root cause: the registry had no explicit state for a batch whose local work can stop while an external runtime/authority gate remains open.
- Why existing checks did not prevent it: previous batches had only used the original three-state lifecycle.
- Fix: extended `BatchStatus` with `external_gate`; retained `current_batch` selection as the sole batch with `status == in_progress`.
- Security/tenant review: reporting/type-only change; no runtime tenant data path changed.
- Regression evidence: focused Mypy for `phase36_program.py` passes; Phase 36 governance tests pass `13/13`; backend capability + Part 1 tests pass `6/6`.
- Rollout/rollback: source-only; revert the status extension if the program model is redesigned.
- Residual risk: the 32 unchanged-module Mypy findings remain existing technical debt outside this Part 1 scope and are not claimed resolved.

### 36H-P1-004 — First protected CI run found two Part 1 regressions

- Date/time: 2026-08-24T09:10Z.
- Environment/component: protected PR #491; root zero-dead/market-readiness audit and VIP browser boundary test.
- Visible symptom/user impact: `Core Owner / Release / Web Contracts` failed because `RedisRealtimeBackplane.stop()` used a bare `pass` in `CancelledError` handling, which violates the repository zero-dead-code audit. `Owner and VIP browser boundaries` failed because the mocked `current_batch` was updated to `36H` while one visible assertion still expected `36G`. Production was not deployed or changed.
- Detection/reproduction: protected GitHub Actions PR checks plus a local full root-suite reproduction for the zero-dead finding.
- Root cause: Part 1 changed the batch lifecycle label and added cancellation handling but did not update the corresponding browser assertion or account for the repository's explicit bare-pass prohibition.
- Why existing checks did not prevent it: the initial focused test set did not include the browser spec or the root zero-dead/market-readiness audits.
- Fix: updated the VIP assertion to `36H`; replaced the cancellation `try/except/pass` with `asyncio.gather(..., return_exceptions=True)`.
- Security/tenant review: no tenant/security boundary weakened; the distributed transport remains dormant and production-unwired.
- Regression evidence: zero-dead + market-readiness + Phase 36 governance focused set passes `18/18`; backend capability + Part 1 passes `6/6`; Ruff and focused Mypy pass.
- Rollout/rollback: fix is source-only on PR #491; no production rollout occurred.
- Residual risk: the refreshed protected CI run remains authoritative before merge.

## 11. Part 2A — Durable admission schema

Status: **merged as PR #492; source/schema verified; production migration intentionally not applied**.

Part 2A adds Alembic `20260824_0040` and four durable tenant-scoped authorities: `realtime_tenant_quotas`, `realtime_rooms`, `realtime_participants`, and `realtime_admission_grants`. Admission credentials remain hash-only, grants are bounded and single-use, and room/participant/grant relations use composite `(resource_id, organization_id)` foreign keys so PostgreSQL—not only service code—rejects cross-tenant links.

A disposable PostgreSQL 18 acceptance passed `0040 -> 0039 -> 0040`, with table presence `4 -> 0 -> 4`, supporting unique constraints `3 -> 0 -> 3`, ten actively rejected invalid tenant/bounds cases, zero accepted cross-tenant links, and no raw admission credential persistence. Evidence SHA-256: `8b2ae400e54b3322d012074f0ff49dcf97fb41a4edb575f59977fa4e939e6ed1`.

Part 2A does not implement the admission service, presence leases, quota counters, API routes, SFU/TURN/recording integration, production migration, production restart, provider request, or load certification. Those boundaries remain fail-closed. The detailed receipt is `docs/phase-36/receipts/36H-2026-08-24-realtime-admission-schema.md`.

## 12. Part 2B — Transactional admission, backpressure and presence fencing

Status: **source implemented and isolated runtime verified; production remains unwired and unmigrated**.

Part 2B adds `app.realtime.admission.RealtimeAdmissionAuthority`, using the tenant quota row as the database serialization boundary so independent API nodes make one consistent room/admission decision without a process-local lock. Room creation is idempotent and bounded by tenant room/participant policy. Admission enforces per-tenant and per-room participant limits, publisher and screen-share limits, and a durable rolling-window admission-rate limit before creating a short-lived single-use grant.

The internal grant bearer value is deterministic HMAC authority material derived from the grant UUID and the existing application secret; PostgreSQL stores only its SHA-256 digest. An idempotent retry can therefore reproduce the still-valid grant without persisting raw credential material. Consumption is row-locked, tenant-scoped, expiry/revocation checked, and single-use. No provider token, SFU room identifier, or external request is created in Part 2B.

Alembic `20260824_0041` extends `realtime_participants` with `presence_fencing_token` and `presence_lease_expires_at`. Presence claim, heartbeat, release and stale-lease reaping require the current node/fencing token. A live lease blocks takeover by another node; an expired lease can be taken over only with a strictly newer fencing token, so stale heartbeats/releases fail closed. The existing room fencing token also has an atomic row-locked advancement operation for future provider ownership.

Isolated PostgreSQL 18 validation passed `0041 -> 0040 -> 0041`; both presence columns, the non-negative fencing check, and both presence indexes disappear on downgrade and return on upgrade. Focused 36H/backend tests pass `15/15`; Phase 36 governance + zero-dead + market-readiness tests pass `18/18`; Ruff and focused Mypy pass. A two-session concurrency test demonstrates that the per-tenant quota lock serializes simultaneous admission attempts: with capacity one, exactly one request is accepted and the other receives participant backpressure.

Not completed in Part 2B: no production migration `0040/0041`, no public/user realtime admission API rewire, no LiveKit/SFU/TURN/STUN/Egress activation, no screen-share media path, no provider credentials, no firewall/DNS/tunnel change, no service restart, no provider request/spend, and no 1000-user or failover certification. Those remain later 36H gates.

### 36H-P2B-001 — Repository-root dotenv polluted the first schema validation

- Date/time: 2026-08-24T12:21Z.
- Environment/component: local source validation only; Backend Settings loading.
- Symptom/impact: the first schema pytest collection raised a Pydantic Settings error before tests ran; production was unaffected.
- Detection/reproduction: running Backend pytest from `/opt/AIOS` caused Settings to load the repository-root `.env`, whose legacy Telegram allow-list value is not valid JSON for the current `List[int]` field.
- Root cause: Settings resolves `.env` relative to process working directory; the validation command used the repository root instead of the Backend directory.
- Why prior tests did not prevent it: CI and normal Backend validation execute with explicit environment/service settings and do not depend on that root dotenv value.
- Fix: reran the tests from `web-dashboard/backend` with explicit `ENVIRONMENT=test`, synthetic `SECRET_KEY`, and disposable test `DATABASE_URL`.
- Security/tenant review: no production secret was read or copied and no tenant record was accessed.
- Regression evidence: schema tests passed `5/5`; later combined 36H tests passed.
- Rollout/rollback: validation-only; no rollout or rollback required.
- Residual risk: the legacy root dotenv value remains unrelated configuration debt and is not modified in 36H.2B.

### 36H-P2B-002 — First disposable PostgreSQL port was already occupied

- Date/time: 2026-08-24T12:23Z.
- Environment/component: isolated PostgreSQL 18 test container startup.
- Symptom/impact: Docker rejected `127.0.0.1:55441` before the disposable container could start; production was unaffected.
- Detection/reproduction: Docker returned a host-port bind conflict; `ss` confirmed an existing listener on 55441.
- Root cause: the chosen local test port was already allocated by an unrelated process/environment.
- Why prior checks did not prevent it: no fixed exclusive port reservation exists for disposable developer test databases.
- Fix: used unused loopback port `55491`; the PostgreSQL 18 container then started and all migration/runtime tests passed.
- Security/tenant review: binding remained loopback-only; no firewall, production Docker network, or production database changed.
- Regression evidence: `0041 -> 0040 -> 0041` passed and the test container was removed after evidence capture.
- Rollout/rollback: test-only; container removal completed.
- Residual risk: future disposable tests should probe/select an unused loopback port before start.

### 36H-P2B-003 — One closing Ruff command used repository-relative paths from Backend cwd

- Date/time: 2026-08-24T12:38Z.
- Environment/component: final local static validation only.
- Symptom/impact: Ruff returned four `E902 No such file or directory` findings without inspecting source; no product/runtime impact.
- Detection/reproduction: the command ran from `web-dashboard/backend` while still passing paths prefixed with `web-dashboard/backend/`.
- Root cause: command working directory and path convention were inconsistent.
- Why prior checks did not prevent it: earlier Ruff commands had run from repository root.
- Fix: reran from Backend with Backend-relative paths.
- Security/tenant review: no runtime interaction.
- Regression evidence: corrected Ruff PASS, focused Mypy PASS, static migration/schema tests `2/2` PASS, Alembic head `20260824_0041`.
- Rollout/rollback: validation-only.
- Residual risk: none beyond normal command-cwd discipline.

### 36H-P2B-004 — Protected Backend CI retained the previous Alembic-head expectation

- Date/time: 2026-08-24T12:41Z.
- Environment/component: protected PR #493 Backend Tests.
- Symptom/impact: Backend CI reported `1 failed, 95 passed`; production was not deployed or changed.
- Detection/reproduction: `tests/test_database_settings.py::test_backend_exposes_the_shipped_alembic_head` expected `20260824_0040` while Alembic correctly exposed new head `20260824_0041`.
- Root cause: Part 2B added a new linear migration but the explicit shipped-head regression assertion was not updated in the first commit.
- Why prior focused tests did not prevent it: the Part 2B focused set covered the new migration and service but did not include `test_database_settings.py`.
- Fix: update the explicit expected shipped head to `20260824_0041` and add that test to the local closing gate.
- Security/tenant review: test-only correction; schema/runtime policy is unchanged.
- Regression evidence: targeted database-settings test passes locally; refreshed protected CI is required before merge.
- Rollout/rollback: no rollout occurred; PR remains unmerged until refreshed CI is green.
- Residual risk: none beyond normal future migration-head maintenance, now included in the Part 2B closing gate.

### 36H-P2B-005 — First CI-incident report append used Backend cwd

- Date/time: 2026-08-24T12:44Z.
- Environment/component: reporting command only.
- Symptom/impact: the first command that attempted to append the PR #493 incident could not find repository-root `docs/` and `.deployment-backups/` paths because its working directory was `web-dashboard/backend`. The targeted code test in the same invocation still passed.
- Detection/reproduction: shell/path errors were emitted before the targeted pytest result.
- Root cause: report paths were repository-relative while the command cwd was Backend.
- Why prior checks did not prevent it: report writes and Backend tests were grouped into one command with different path roots.
- Fix: repeat report writes from `/opt/AIOS`; keep Backend-only validation commands separate.
- Security/tenant review: no runtime or tenant data access.
- Regression evidence: report files updated from project root and hashes regenerated before the next commit.
- Rollout/rollback: reporting-only; no rollout.
- Residual risk: none.

### 36H-P2B-006 — Closing reporting checker was invoked from Backend cwd

- Date/time: 2026-08-24T12:46Z.
- Environment/component: local validation orchestration only.
- Symptom/impact: `scripts/check_phase36_reporting.py` was not found because the command cwd was `web-dashboard/backend`; `set -e` stopped the grouped command before its targeted pytest step.
- Detection/reproduction: shell returned file-not-found for the repository-root reporting checker.
- Root cause: repository-root and Backend-only validation were grouped under the Backend working directory after the previous path issue.
- Why prior correction did not prevent it: the report-write path issue was fixed, but this separate grouped validation command still retained Backend cwd.
- Fix: permanently separated the commands: reporting + `git diff --check` from `/opt/AIOS`, Backend pytest from `/opt/AIOS/web-dashboard/backend`.
- Security/tenant review: no runtime access.
- Regression evidence: reporting invariant PASS for 9 changed paths; shipped Alembic-head test PASS `1/1` from Backend cwd.
- Rollout/rollback: validation-only.
- Residual risk: none.
