# FR09 - reversible live Backend CPU budget increase without restart

Protected source baseline: a45f3442c2b2096bde0701acd93a7046e0649cda.

## Concrete live change, 2026-10-24

After validating 36 running containers (35 healthy) including 23 healthy worker
containers, the NEW host operator increased the existing production Backend
container CPU quota from **4.0 to 8.0** through Docker's live CPU cgroup update.
It did not change memory, worker count, PostgreSQL connection pool limits,
image, container ID, start time, Docker restart count, credentials, or data.
All four checked private/public gateway HTTP boundaries returned HTTP 200.
The separately delivered opt-in Frontend CPU overlay was also already active
at 3.0 CPUs on the existing Frontend cgroup, without restart.

Immutable before/after receipt (outside source-controlled secrets):
/var/lib/aionex-migration/launch-continuation-20261024T153506Z/fr09-live-backend-cpu8-no-restarts/FR09-PRODUCTION-BACKEND-CPU8-WITHOUT-RESTART.json
sha256 183f95fea13ce544fa6f59e2d07989148b97420c24f2777e349cc5faa704ae34.

## Source persistence for a later guarded Compose lifecycle

Use docker-compose.fr09-backend-cpu.yml **only as an opt-in overlay** when
performing a separately approved production Compose deployment. It overrides
only services.backend.cpus: "8.0". It does not modify the protected base
docker-compose.production.yml or enable any optional worker profiles.

No production Compose up, build, pull, restart, DNS mutation, or
service replacement occurred in preparing this change. A live Docker CPU
budget is transient across container recreation unless the opt-in overlay
is included in a future Compose invocation. Keep the legacy CPU4 baseline
unchanged so historical FR06 source checksums remain valid.

## Scope and residual acceptance

CPU allocation is not a benchmark result. FR09 full admission still requires
5000 authenticated concurrent users, 3 projects + 3 conversations per user,
15000 durable jobs over 15 minutes, ordinary-read P95 at most 500ms, enqueue
P95 at most 1000ms, tenant segregation, no provider charges, and original release
gates. Passing targeted source tests or observing healthy live services
does not establish those results.
