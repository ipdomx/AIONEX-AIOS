# FR09 - one live-DB authorization query and 8 pool-safe API workers

Protected main baseline: e3691a03fb8662c219aa8da9029b65a6abade92d.

## Change
Authorize in one live SQL statement joining User, Role, Organization, RolePermission
and Permission, not trusting JWT claims or caching role revocation. The existing
refresh_cached/populate_existing path preserves cross-transaction Owner revocation.
The optional backend-only Compose overlay raises WORKERS from 4 to 8 with
pool_size=6 and max_overflow=1. Total allowed API PG connections remain 56 <= 60.
The historical production base Compose, workers, PostgreSQL, Cloudflare and Nginx
are unchanged by this source-only change.

## Independent measurement
- 63 PostgreSQL16 security, permission-revocation and conversation tests passed.
- Five thousand actual synthetic auth accounts across 100 orgs, 15000 projects,
  15000 tasks and 15000 conversations, 250 max in-flight requests.
- Isolated PG16 CPU16 and API CPU8: baseline 8 workers P95 in milliseconds was
  conversations 1027.1, projects 538.64, identity 322.77. New single-query
  authorizer with same 8 workers: conversations 749.72, projects 479.3,
  identity 250.79. Every route returned 5000 / 5000 HTTP200.
- In an additional 4-worker A/B/B/A, the project route improved ~15.9 percent
  but the conversation route only ~0.8 percent. Thus the 8-worker setting is
  part of the measured improvement, not optional for the performance claim.

## Hold boundaries
This is not proof of 5000 simultaneous authenticated HTTP connections,
fifteen minutes of full mixed load, 15000 successfully queued and executed
AI project worker jobs or the 72-hour natural G5 stability gate. Conversation
P95 remains above the 500ms ordinary-read criterion. Do not relabel
provider-neutral completed snapshots as queued external AI model executions.

No production services, secrets, Redis leases or worker tasks were changed
by building or submitting this PR. External provider spend is zero.
