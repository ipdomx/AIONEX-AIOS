# FR-06C5D11A — Telegram worker action admission

Base: accepted main `6c79179a592e43e10c4d795dfa3db48c3818099c` (PR776).
D10 Backend and the eleven media workers are already deployed. FR-07 remains
completed; neither is redeployed by this source/laboratory part.

## Observed gap

Both Owner and user Telegram worker loops could poll, process commands, write
security audits, and persist offsets while maintenance was closed or unavailable.
The user worker additionally registered its remote bot identity before consulting
maintenance. Poll results that arrived after closure were still processed.
The unchanged-source baseline reproduced ten failures among twelve PostgreSQL
worker-loop cases; the two normal open-state controls passed.

## Implemented boundary

The helper uses the existing immutable schema8 authority. It does not add or
rename a versioned scope, seed a missing row, publish a new schema, or upgrade a
runtime claim into full-host coverage. A short admission read prevents another
poll when already closed. A long poll already admitted may finish after closure;
its result must separately acquire action admission before processing.

The shared maintenance lock spans one fetched batch, its original handlers,
replies, business transactions, security audits and durable offset commits.
Bot-identity registration uses the same guarded action boundary. A separate
NullPool engine avoids taking a business-pool connection while the handler
requires another. Its lock-only session is never committed by the handler.
A missing, malformed, older, closed, or unreadable authority fails closed.

No action coroutine is created on denial. An unaccepted batch does not advance
its offset, so the next poll cannot acknowledge away an unprocessed update.
For accepted work, local offset and last-update state advance only after the
existing durable offset write returns. Older/duplicate entries in the same
batch are not executed again. If a later entry fails, earlier committed offset
progress is retained. Stop requests finish the current update without starting
the next entry in an admitted batch.

Before admission, cancellation removes the lock waiter without executing work.
After admission, repeated outer cancellation waits for the same child action to
end; it does not detach, restart, or authorize a second handler. Caller cancellation
is still propagated afterwards. Business commit/rollback cannot release this
independent fence. The worker closes its API client only after run returns,
and disposes the guard engine even if API-client cleanup raises.

Original private-chat, Owner allowlist/second-factor, one-time user link,
current account/auth-generation, tenant and plan/permission checks remain in the
existing handlers; no authorization check or provider permission is weakened.
Closed workers retain health heartbeats and bounded interruptible idle waits.
Health-file writes, startup token loading and initial offset reads are declared
control/startup operations, not payload-processing drainage.

## Verification

Retained phases include the original ten failures, twelve fixed cases, thirty-one
expanded cases, and a preliminary combined set of fifty-two tests including
existing Telegram handler/authentication/security tests. The final expanded suite passed35 cases, and its combined Telegram regression
suite passed56 cases with no failures, errors or skips. These overlapping suites
are not additive. Frozen/source-quality acceptance is retained in the runtime
manifest rather than inferred from the earlier results.
Real PostgreSQL lock waits test both publisher-first and closer-first orderings,
independent inner commits/rollbacks, stale ORM data, cancellation before admission,
repeated cancellation during a real owned storage thread, and offset commit
failure. Loop tests use the real worker loop and durable offset operations with
an explicitly fake Telegram API. Existing tests exercise the original handlers;
additional integrated cases use real rejection/audit paths with fake replies.
All test resources are exclusively owned and disposable; cleanup is verified.

No production row, service image, maintenance generation, token, key, DNS,
Cloudflare policy, or provider endpoint is changed by this part.

## Limits, retained without weakening

This is not a full-host drain proof and not a Telegram exactly-once delivery
protocol. Polls already in flight, shared HTTP-client lifecycle, process death,
independent inner cancellation, and DB-connection loss require separate operational
reconciliation. The existing command-error retry policies are not expanded or
claimed safe for uncertain external sends. No durable provider-delivery ownership
or automatic remote cancellation is added here. A stuck admitted action may
cause the existing bounded close operation to fail rather than declare false
closure. Direct internal calls to a handler do not traverse the worker loop.

New worker images must contain the accepted schema8 maintenance reader as well
as this helper and both loop changes; the presence of schema8 in the database
alone is not proof an old worker image understands it. Activation needs its own
image/security/transition/recovery acceptance. Other producers, retained media
ownership, and the encrypted host-state move remain separate requirements.
The blocked Replicate inventory and blocked postrelease combined verification
are not retried by these source or isolated test operations.

Evidence: `docs/project/runtime/fr06d11a-telegram-admission-20260928/`.
