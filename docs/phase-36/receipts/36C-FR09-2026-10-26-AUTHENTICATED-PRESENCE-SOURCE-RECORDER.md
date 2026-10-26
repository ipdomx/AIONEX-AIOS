# Phase 36C / FR09: actual backend-authenticated WebSocket presence recorder

Date 2026-10-26. Ledger: P36-0089. Scope: source-only, no production change.

## Defect / acceptance gap
PR #988 (merged 57b2ea74) correctly required an HMAC-authenticated,
time-resolved 5000-concurrent-session evidence series, but there was no backend
instrumentation generating that series. Historic 5000 synthetic JWTs and 225000
paced HTTP reads proved a bounded read-path baseline, not 5000 concurrent
authenticated users. A client-side claim cannot be used as evidence.

## Mechanism
- Add an optional FR09 recorder to the *existing* revocable WebSocket route.
  Only after AuthorizedRealtimeSocket.ensure_authorized and hub.connect/accept
  are successfully completed can a connection be counted.
- Idle sockets are revalidated with the existing five-second authorization
  interval; invalid credentials, role/permission drift, disconnects, or revoked
  auth generations cannot refresh the registered presence. Errors fail closed.
- One random server-issued 24-byte connection nonce is stored per websocket.
  Tenant+user+auth_version are HMAC-SHA256 hashed with a separately mounted
  0600 identity key; no raw user IDs, access/refresh tokens, prompts, subjects,
  provider credentials or personal content enter the Redis telemetry namespace.
- Redis Lua updates and cleanup are atomic across multiple API processes.
  An authenticated connection requires a successful refresh within 20 seconds.
  A stale, disconnected or crashed socket is removed from session and distinct
  user counts. The operator can sample the shared namespace, never trusting
  client-provided population claims.
- The collector obtains 32 real Redis snapshots approximately every 29.5 s,
  covering over 900 seconds, and signs one canonical series using a DIFFERENT
  operator-private 0600 HMAC signing key.
- The FR09 verifier now binds a signed series to a unique run ID and compares
  that value to the mixed-workload receipt run ID. Replayed previous-run
  samples fail closed even if the original signature is valid.
- All telemetry is opt-in. Without
  AIOS_FR09_AUTHENTICATED_PRESENCE_ENABLED=true, the existing websocket route
  is functionally unchanged and does not touch telemetry Redis or open keys.

## Scoped deployment configuration (not activated)
- AIOS_FR09_AUTHENTICATED_PRESENCE_ENABLED=true
- AIOS_FR09_AUTHENTICATED_PRESENCE_RUN_ID=fr09-<operator-chosen-id>
- AIOS_FR09_AUTHENTICATED_PRESENCE_KEY_FILE=<independent 0600 owner-mapped secret path>
- A distinct private signing-key file is required by the signed collector.
  Do not reuse SECRET_KEY, provider keys, auth JWTs, or the identity-hash key.
- Deploy only after FR08 independent Owner/customer acceptance and FR25
  generation/cutover policy. Preserve normal 72h stabilization evidence.
- The collector is an internal library with no new public HTTP endpoint, and
  the operator must supervise an isolated, admission-approved 900+ second run.

## Tests and independent lab
- 16/16 focused network-disconnected read-only backend unit tests passed,
  including fail-closed Redis outages, unverified auth rejection, deduplication
  across two sessions for one user, cross-tenant isolation, auth-version
  revocation, no-broad-permission secret files, signed receipt and missing
  sample/gap rejection.
- 160/160 pure Phase36/FR09 evidence/profile/reads/model-policy tests passed.
- Independent encrypted FR09 test-only Docker daemon started a no-network
  Redis 7.4.11 ephemeral instance and executed *real* Lua against 5000
  explicitly SYNTHETIC identities in 100 synthetic organizations. Synthetic
  registrations completed in 1.043 s; exactly 5000 distinct users and 5000
  connection entries were counted. An extra connection for the same user
  incremented connection count to 5001 while distinct users remained 5000.
  A 21-second simulated stale gap yielded zero active connections, with no
  dangling Redis entries.
- The temporary Redis and backend test containers were all removed, lab
  containers returned to 0. Production stayed at 36 running, 35 health
  checked, 0 unhealthy; all four project workers healthy with zero restarts.

## Security and remaining gates
- Key file is read through O_NOFOLLOW and strict regular-file owner/0600
  checks. A signing HMAC proves that a trusted signing key accepted the
  recorded values; independently audit key custody, time-source integrity,
  backend deployment hash and recorder source before acceptance.
- This does NOT prove any actual 5000 user connections or 15000 model-backed
  durable jobs. Simulated data was only a nonproduction telemetry exercise,
  not an FR09 acceptance run. The isolated lab provided no production
  credentials, paid provider requests, external network connectivity or
  customer database access.
- Actual 5000 authenticated user connections, 15-minute mixed workload and
  15000 real AI completions remain not run/proven. FR08 full independent
  recovery, provider quota/cost, 72h natural FR25 and final launch remain HOLD.
- Rollback: do not enable the optional environment flag; if enabled in a
  controlled later rollout, revert the websocket source and clear only its
  dedicated hashed Redis namespace after documented approval. No schema or
  customer data migration is required.


## CI correction 2026-10-26T04:09Z
- The protected initial/follow-up PR #990 Final Validation backend job failed
  at Ruff static parsing, before coverage. Ruff was configured to inspect
  Python 3.8-compatible syntax and rejected two parenthesized multi-context
  blocks in the new tests at original lines 365/393.
- Cause: test-only syntax required Python >=3.9, while isolated backend
  tests used Python 3.11 and never enforced the repository-wide Ruff profile.
- Fix: change only those two test blocks to contextlib.ExitStack, preserving
  mock ordering and all authorization assertions. No lint suppression or
  platform-version downgrade. The earlier CI failure remains in history.
- All protected CI checks must still pass before protected merge. No production
  restart, customer data write, paid provider request or active load.
