# FR-07B/C/D2/E — Governed project conversations and both dashboards

Base: accepted PR769 source `690bc0c08fe55234fc24ff212d07a43ee3cd21fd`
(same application tree as its candidate `043080eb`). Deployment status belongs
only to the canonical Project Hub journal. This receipt records the source and
isolated acceptance; it does not itself declare FR-07 or the final release closed.

## User-visible function

The authenticated portal now has a real `/[locale]/conversations` page and
navigation entry in all six portal languages. A user creates an independently
persisted conversation associated with one of their organization's projects,
selects a configured assistant, submits messages, and receives durable job
results. Reloading, changing projects or reconnecting cannot reset the original
conversation timestamp or usage counters. Multiple conversations can remain open
subject to the current Owner policy. Closed/paused history is retained.

No canned reply is substituted when a provider is missing. Free users can use a
configured local Ollama assistant only. Paid users must explicitly authorize
external processing before a non-local assistant is used. Dedicated 3D providers
and the deferred AWS/Azure integrations are not routed through this text API.
An explicitly configured platform-owned assistant may be shared; ordinary agent
identities remain tenant-scoped. A queued turn remains bound to the accepted
provider identity/type and model, and cannot silently switch to a replacement
assistant if its original agent is deleted.

The Owner dashboard adds `/owner/conversation-governance`, with the existing
Owner navigation, bilingual interface translation system and server-protected
API. It exposes global, plan and user overrides; current usage; assistant
selection; audit notes; and pause/resume/close controls. Existing `/users` controls
continue to own account bans, suspension, roles and account restoration. An
administrator can inspect or close a banned user's conversation without
re-enabling that account; resuming still requires current live-user permission.

## Policy and exact boundaries

Policies reuse `OwnerControlRecord`; messages and asynchronous turns reuse the
existing durable `Job` table. No database migration is introduced.

Numeric precedence is global, then plan, then user. Any disabled policy layer
blocks new governed work; a lower layer cannot cancel a higher-layer suspension.
Policy edits use expected-version compare-and-swap and a shared/exclusive
transactional guard. Concurrent consumers use the database user-row lock and
current policy instead of stale in-memory snapshots. Database time controls UTC
day rollover and conversation duration. The browser's timer is only a display,
computed from the server's remaining duration and monotonic elapsed time.

The Owner controls projects per user, simultaneous conversations per user and
project, duration, messages per conversation, messages per UTC day, cumulative
message credits, message length and dispatch priority. Credits count accepted
user turns, not money or payment authorization. Resetting an override or restoring
access never refunds, erases or resets the ledger. Existing free-tier and billing
entitlement limits remain additional constraints and are still Owner-governed
through their original controls; this change does not enable payment collection
or silently override commercial entitlements.

The regular project-create path and the Owner create/restore-from-deleted path
share a serialized capacity check. A suspended requester cannot bypass its own
policy by selecting another project owner. The existing project-execution and
native agent-execution request paths also charge the user's daily/cumulative
turn budget before commit. Provider-neutral internal project bookkeeping is not
misrepresented as an external AI turn.

Creating or resuming conversations rechecks current user/project caps. Resume
never grants a fresh lifetime or resets counters, and cannot reclaim a slot that
another conversation already consumed. Archived/deleted/cancelled projects cannot
accept new messages. Bound entity identifiers preserve previously deployed IDs
such as `owner-1`; newly created conversation and turn identities remain UUIDs.

## Dispatch, ambiguity and revocation

One durable turn may be in flight for a conversation. Idempotent retry with the
same request/body returns the same Job and does not charge a second time. Changed
content under the same request identity is rejected. The worker selects queued
turns by Owner priority, serializes admission, revalidates current policy,
authentication version, account/role/organization, project state, original
assistant binding and conversation duration before it changes the Job to
`running` and commits. Only after that commit can provider I/O start.

A queued turn that is invalidated before dispatch is cancelled. A running job is
not automatically adopted or retried after restart. Cancellation, an uncertain
provider response or loss of worker control does not become a success or a
permission to replay. `needs_review` prevents an automatic new turn on the same
conversation. Accepted usage remains charged; administrative investigation can
use the retained identity and audit evidence.

The generation of content by a remote provider already dispatched before a
policy change cannot be recalled. The source does not claim cancellation of such
remote computation. Policy changes stop subsequent admissions and governed
queued dispatch, and message/history access respects the current user authority.
This is distinct from revoking an already-transmitted WebSocket frame.

The two event-stream routes retain the PR769 JWT/session/role/organization checks.
Their authorization reader also applies global/plan/user governance to every
outbound authorization and idle revalidation. A suspended user cannot reconnect
with the same credential. Re-enabling policy requires a new socket; it does not
resurrect the closed connection or reset usage. LiveKit audio/video room admission
is a separate existing feature, not this text-conversation transport.

## Executed source and transport acceptance

The combined new governance, counter/policy and event-stream suite passed **134
cases** using real isolated PostgreSQL, real WebSockets and a Redis backplane,
without errors or skips. Worker provider calls inside these unit/integration
cases are explicit test doubles, not evidence of real AI quality.

Independent review first reproduced eight failures out of ten cases: resume
bypassed a now-full slot, archived projects could be charged, malformed service
request identities were accepted, a suspended requester could create for another
owner, a lowered message limit did not block a queued turn, and malformed usage
could be presented. A further two administrative tests reproduced stale Owner
control and inability to close a banned user's conversation. These were fixed
and the regression cases retained. Four additional tests reproduced stale Owner
identities in policy update/reset and directory/history reads; these service
boundaries now refresh the durable principal and reject the revoked version. The unchanged failures remain in the runtime
evidence, not reclassified as infrastructure successes.

Two legacy integration cases correctly failed because their dependency-injected
actors claimed permissions that were absent from their database roles. The test
fixtures now persist only the actual `projects:read` and `projects:write` grants;
the runtime fresh-authority checks were not relaxed. The **44-case legacy
Owner/project/execution regression** then passed. Additional cases cover legacy
non-UUID identifiers and reject path/control-character/unbounded identifiers.

Five HTTP cases use actual FastAPI route validation, RBAC, PostgreSQL
transactions, compare-and-swap, duplicate admission and cross-tenant rejection;
only the authenticated fixture principal is supplied by the test dependency.
JWT/cookie validation is separately exercised by the real browser and WebSocket
acceptance below.

## Real browser acceptance (not a real AI-provider benchmark)

The public Nginx API allowlist now includes only the exact user conversation
contracts; it does not expose the Owner policy API. The prior allowlist would
otherwise have returned 404 for the new portal requests. An isolated syntax and
route-boundary check was executed with the pinned production Nginx image.

Both production-profile frontend builds were exercised in a real headless
Chromium browser against the real API, signed synthetic cookies, PostgreSQL and
Redis on an exclusively owned internal Docker network. The three hostname aliases
resolve only inside that network; no public DNS, live credential, customer record
or production application configuration is used. Ports are not published.

The provider transport is an explicitly identified synthetic Ollama-compatible
HTTP service. The application worker and durable output path are real, but the
fixture reply is not claimed as AI inference, a production provider test or a
quality benchmark. No media devices, audio, video, Egress or public-provider
requests occur in this laboratory.

Eleven assertion groups passed: Owner user-policy creation; authenticated user
conversation and asynchronous reply; manual request rejection beyond the cap;
reload continuity; Owner pause/resume without resetting age; daily limits shared
across conversations; cumulative credits independent of the daily cap; database
expiry after shortening duration; immediate subsequent access denial on Owner
suspension; restoration without a credit reset; and desktop/mobile layout checks
on both dashboards. Three completed Jobs, exactly three charged turns and nine
Owner audit records were independently checked in the database. No queued,
running or unresolved test Jobs remained. All six owned containers/network
resources were removed and their absence verified.

Initial browser runs failed on a read-only HOME and on Selenium interaction with
smooth scrolling/asynchronous confirmations. The fixture gained a private tmpfs
HOME, explicit instant centering before real pointer clicks, and proper waits
for enabled controls and native confirmations. No JavaScript click bypass,
confirmation bypass, product permission relaxation or hidden retry was used.

Screenshots, browser logs, failed and successful runs and source hashes are in
`docs/project/runtime/fr07-governed-conversations-20260927/browser-acceptance-v6/`.

## Frontend provenance and deployment gate

The user lock requires Next **15.5.24**, while the preexisting shared host
`node_modules` contained 15.5.22. The first host build is retained but explicitly
not approved for release. Fresh lock-exact dependencies were installed in
separate non-root staging, without changing production `node_modules`.

The final artifacts were built in the pinned Node Alpine image, as an unprivileged
user with a read-only container filesystem, writing only to dedicated host build
folders. User Next15.5.24 and Owner Next15.5.25 match their locks. Both builds
include production standalone output; the user build additionally contains the
six-language static export. Type checking, linting, portal integrity/static smoke
and Owner API-contract/Arabic coverage checks passed. No full Docker image build
was allowed to fill the small encrypted container-runtime volume.

Protected candidate CI, exact post-merge main acceptance, immutable delta-image
source verification, fresh encrypted recovery, actual provider readiness, selective
Backend/Owner/portal deployment and post-deployment acceptance remain separate
requirements. This source receipt does not mark them complete in advance.

## Gateway-inclusive acceptance and completion inventory

The full eleven-group browser workflow also passed through the real pinned
production Nginx binary with the exact updated allowlist. Unauthenticated user
conversation access reached the API and returned401, while the Owner policy API
and an unlisted subroute remained404; a forged private-channel request header
did not bypass this boundary. All seven specifically owned lab resources were
removed and their absence checked. Retained results and screenshot evidence are
in `gateway-browser-acceptance/` under the runtime evidence directory.

The first full root suite reported four source-inventory assertions: the three
new routes/pages had not yet been registered, and an existing Studio route-list
assertion did not include the newly added conversation alternative. The explicit
completion-resource maps now assign these new resources to FR-07, without
changing the historical Phase29 feature completion percentage. The Studio test
retains every previously required protected route and additionally includes
conversations. No runtime guard or test coverage was removed.
