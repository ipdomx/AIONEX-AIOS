# FR09 2026-10-25: authenticated user, project, conversation A/B/B/A

Scope: synthetic 250-manager cohort in one isolated tenant; 750 real PostgreSQL
project rows, 750 tasks, and empty per-user conversation inboxes.
The existing client executed 250 authenticated HTTP reads for each of three
routes in each of four phases, or 3,000 verified HTTP 200 responses. The
encrypted isolated Docker daemon and synthetic JWT credentials did not touch
production customers, providers, or public networks. Synthetic JWTs were
deleted, lab containers removed, and production container identities matched.

Control and candidate were compared on the same PostgreSQL/Redis data:
PostgreSQL 16 isolated with 12 CPU limit, eight API workers, API CPU limit 8,
API memory limit 4GiB, database pool 5+2 per worker with total ceiling 56/60.
The sequence was control / candidate / candidate / control.

| Authenticated read P95 | Control A | Candidate B | Candidate B2 | Control A2 | Control mean | Candidate mean | Reduction | Both candidate runs <=500ms? |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| identity | 693.94ms | 689.02ms | 649.22ms | 756.16ms | 725.05ms | 669.12ms | 7.7% | no |
| projects | 469.48ms | 371.64ms | 451.18ms | 449.46ms | 459.47ms | 411.41ms | 10.5% | yes |
| conversations | 898.99ms | 655.51ms | 685.73ms | 701.31ms | 800.15ms | 670.62ms | 16.2% | no |

Code changes: aggregate live RolePermission grants into a single per-user
PostgreSQL array without caching revocable authority; obtain database clock
with the conversation list statement rather than an extra SQL roundtrip;
count active project tasks with COUNT(*) and both tenant/project predicates
to match the existing composite (organization_id, project_id, status) index.

Important distinction: only the authenticated *project read* path met the
500ms P95 threshold twice at the 250-user stage. Authentication and
conversation list still exceeded the SLO. These results are not proof of
5,000 mixed concurrent authenticated users, 15,000 completed durable
project executions, 15,000 real LLM inferences, 15-minute full mixed
steady state, or 72 hours of natural production stability.

An additional isolated 16-worker/24-CPU candidate did not improve the full
three-route mix and was rejected as an unverified production scaling choice.
No code or resource change was deployed to production by this test.

Full release status: HOLD, FR09/FR25 not accepted.

Evidence JSON SHA256: 559a8561d7ef8972959facf8ae8ed2d8cde50de2ba9ea1a779e60dc6330336e5
Driver result SHA256: 559a8561d7ef8972959facf8ae8ed2d8cde50de2ba9ea1a779e60dc6330336e5

### Rejected follow-up optimization (not shipped)

A further combined Owner-policy/identity SQL statement was evaluated on
the *same* four-phase isolated mixed-read profile. It regressed the mean
P95 across all three routes: identity 712ms to 773ms, projects 470ms
to 547ms, and conversations 704ms to 907ms. The joined Owner policy
proposal was reverted. This rejected run is available as an independent
hashed failure-to-improve receipt. Do not merge or deploy it.

Passing 13 standalone unit checks covers live role, user and organization
revocation, empty inbox clock read, and tenant-scoped task counts. The
acceptance SLO requires positive full mixed load tests, not just unit pass.
