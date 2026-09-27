# FR-07D1 — Revocation of already connected event streams

Source base: accepted and deployed `820f78e4c09a71b5553357e1ff17c789d5c011ca`.
Canonical deployment and completion status is recorded in the Project Hub runtime
journal, not inferred from this source receipt.

## Reproduced behavior

Seventeen independent loopback WebSocket cases failed against unchanged source.
The first ten delivered an event after a committed user suspension/ban/deletion,
auth-version change, tenant reassignment, organization suspension, free-plan
transition, role suspension/removal or permission removal. Separate cases showed
idle access-token expiration/logout, reconnect and authentication outage were not
handled by the established connection. The old `/ws/{client_id}` accepted directly
at the application; Nginx already denies that path, so this is not evidence of a
publicly exploitable proxy route or an observed customer incident.

## Correction and safety boundary

Only an `AuthorizedRealtimeSocket` is enrolled in the tenant hub. It revalidates
the signed token through the existing Redis-backed logout check and reads the
current user, organization, role and permissions in a fresh DB session before
accepting or sending any JSON frame. A changed principal closes that connection;
a reconnect must pass the current state again. Empty permissions and unassigned
roles cannot reacquire a stream. Raw credentials are held only for that socket's
lifetime, not logged/persisted, and are cleared on closure.

An idle stream revalidates every five seconds. Auth and send/close I/O each have
three-second bounds. The operational guarantee is a fresh check for each frame
and bounded idle reevaluation, NOT instantaneous recall of a frame already admitted
before a competing revocation. This part governs the event stream, not a LiveKit
media connection or a project conversation's time/message limits.

The application now denies the legacy anonymous global broadcast path before
accepting a connection. Existing Nginx boundaries are unchanged.

The real tests also exposed an existing Redis listener self-cancellation cycle
when its delivery callback removed the final subscriber. Channel unsubscribe is
now ordered under the subscription lock. A retired listener exits after its
current callback and never cancels/gathers itself; fresh subscriptions start a
new reader. Tests assert no retained listener tasks after cleanup.

## Acceptance

The initial seventeen cases were repeated unchanged: all passed after correction.
The first corrective run exposed recursive listener cancellation at teardown;
that run is preserved, not silently counted as clean acceptance. The expanded
suite includes fresh reconnect denial, multiple sockets for one account, and a
successful new subscription after the final revoked client. Twenty-three new
cases and ten existing Realtime regressions pass together (33 total).

Uvicorn's real WebSocket transport, signed synthetic tokens, real isolated
PostgreSQL schemas and Redis Pub/Sub are used, including publication from a second
runtime instance. Auth-store outage is an explicitly injected negative control.
No customer, production token, provider or media device is involved. Full Ruff
app/tests/main.py and Mypy app pass; final root-suite/CI status is retained in the
canonical runtime receipt.

Evidence: `docs/project/runtime/fr07d-event-stream-revocation-20260927/` includes
before/after JUnit, logs, source hashes, exact image IDs and cleanup checks. A read
of a pre-existing transport test was blocked by the tool before execution and was
not retried through another path; these are independently authored tests.

## Not closed by this part

FR-07B/C conversation lifetime/message quotas, plan/user exceptions and project
creation bounds, and both dashboard acceptance remain separate requirements.
FR-06 host-state/TURN/producer drain is not asserted. No migration or production
change occurs by merely merging this source.

## Protected CI transport fixture compatibility

The first protected run failed in the pre-existing transport-only test because
its synthetic auth service returned a partial object with no organization plan
or permissions. A later read through the same MCP `read_file` action succeeded;
no alternative source-access route was used. The fixture now supplies those two
real UserRecord contract fields. Transport, authentication, connected-count and
ping/pong assertions remain intact. Production authorization was not weakened,
and no test was skipped or disabled. The initial CI failure is retained in the
runtime evidence rather than rewritten as success.
