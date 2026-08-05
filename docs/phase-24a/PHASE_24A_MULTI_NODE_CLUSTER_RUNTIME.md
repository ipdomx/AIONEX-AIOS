# Phase 24A — Multi-Node Cluster Runtime Simulation

## Status

Phase 24A completed successfully on 2026-08-05.

A three-node AIOS cluster was built and executed inside an isolated Docker network on the current server. The simulation exercised real encrypted inter-node communication, authenticated service discovery, shared durable state, leader election, leader failover, worker heartbeats, task leases, task recovery after a forced node crash, node rejoin, idempotency, and final Chief Engineer review.

Final result:

- execution ID: `phase24a-multi-node-project-cycle`;
- approved: `true`;
- readiness score: `1.0`;
- tasks succeeded: `6/6`;
- recovered leased tasks: `1`;
- dead letters: `0`;
- initial leader: `node-a`;
- replacement leader: `node-c`;
- failed and rejoined node: `node-a`;
- workers completing tasks: `node-b`, `node-c`;
- total simulation duration: approximately `19.82` seconds;
- production modified: `false`.

## Scope

Phase 24A validates the cluster design before introducing additional physical servers.

It adds:

- three independent Docker node processes;
- an internal-only Docker network;
- HTTPS between nodes using a short-lived simulation CA;
- HMAC-SHA256 authentication for every cluster control request;
- service discovery through configured peer identities and shared membership state;
- worker and node heartbeats;
- durable SQLite queue and shared cluster state;
- leader leases and monotonically increasing leader terms;
- task leases with heartbeat renewal;
- recovery and redistribution when a task owner disappears;
- dead-letter handling after bounded attempts;
- idempotent task submission;
- aggregation of six distributed department results;
- final `EngineeringOrganization` Chief Engineer review.

This is a controlled single-server cluster simulation. It does not claim cross-datacenter behavior or production deployment across multiple physical hosts. Those belong to Phase 24B.

## Added implementation

### `src/aios/cluster_runtime/auth.py`

Provides HMAC-SHA256 request signing and verification.

The canonical signature includes:

- node identity;
- HTTP method;
- request path;
- timestamp;
- SHA-256 of the request body.

Requests outside the allowed clock-skew window or with modified bodies are rejected. The shared secret is never included in `repr` or responses.

### `src/aios/cluster_runtime/client.py`

Provides the HTTPS-only inter-node client.

It:

- rejects non-HTTPS URLs;
- validates the simulation CA and peer hostname;
- signs every request;
- returns only sanitized failures;
- records TLS and authentication evidence.

### `src/aios/cluster_runtime/state.py`

Provides shared SQLite cluster state for:

- node registration;
- service URLs and capabilities;
- heartbeat timestamps and node state;
- leader lease and term;
- leader history;
- secure peer observations;
- cluster audit events.

Leader changes use `BEGIN IMMEDIATE` transactions so only one node can acquire an expired lease.

### `src/aios/cluster_runtime/node.py`

Provides one independent cluster node process.

Each node runs:

- a TLS HTTP service;
- node and worker heartbeat loops;
- leader election and leader-only maintenance;
- secure peer discovery;
- a leased task worker;
- source-evidence hash verification;
- task lease renewal while work is active.

The node process runs as UID/GID `10001`, with a read-only container filesystem, no Linux capabilities, and `no-new-privileges`.

### `src/aios/cluster_runtime/cycle.py`

Provides the six-department multi-node project cycle.

It:

- accepts only approved Phase 22D evidence;
- verifies every source receipt hash;
- submits exactly six idempotent tasks;
- waits for terminal task state;
- proves failover and lease recovery;
- rebuilds engineering evidence from completed task results;
- performs the Chief Engineer review;
- writes immutable runtime evidence under an absolute `/var/tmp` root.

### `deploy/phase24a/`

Contains:

- a non-root Dockerfile;
- a three-service Compose definition;
- an internal-only Docker network;
- loopback-only host port bindings;
- read-only TLS, secret, and source-evidence mounts;
- container health checks.

### `scripts/phase24a/run_docker_simulation.py`

Provides the reproducible validation harness.

It:

1. creates short-lived TLS material and an external HMAC secret;
2. copies approved evidence into a read-only simulation mount;
3. builds the non-root node image;
4. seeds the six department tasks;
5. starts `node-a` first so it becomes leader and leases the controlled slow task;
6. starts `node-b` and `node-c` and verifies all secure peer pairs;
7. sends `SIGKILL` to `node-a` while it owns the task;
8. waits for a new leader and lease expiry;
9. verifies another node completes the recovered task on attempt two;
10. restarts `node-a` and verifies secure rejoin;
11. writes the final evidence and runtime log hashes;
12. removes the temporary containers and network.

## Actual failover evidence

The actual run established:

- leader term 1: `node-a`;
- forced crash: `node-a` via `SIGKILL`;
- leader term 2: `node-c`;
- recovered task: Architecture;
- original owner: `node-a`;
- final owner: `node-c`;
- final attempt count: `2`;
- duplicate final completion: prevented;
- final task state: `succeeded`.

All six directed peer pairs were observed as:

- healthy;
- TLS verified;
- HMAC authenticated.

## Runtime evidence

Runtime evidence is stored outside Git at:

`/var/tmp/aionex-phase24a/evidence/phase24a-multi-node-project-cycle`

The retained state and runtime evidence are under:

`/var/tmp/aionex-phase24a`

The final evidence includes:

- `manifest.json`;
- `REPORT.md`;
- six department task receipts;
- node log hashes;
- internal-network inspection hash;
- leader history;
- secure peer observations;
- task attempt and worker ownership records.

No TLS private key, HMAC secret, provider key, raw provider request, or production secret is committed to Git.

## Tests

Phase 24A unit and contract tests:

- `24 passed`.

Combined controlled Phase 22C, Phase 22D, Phase 23, and Phase 24A regression boundary:

- `151 passed`.

Coverage includes:

- HMAC signing, tampering, timestamp, and redaction;
- membership and service discovery;
- leader renewal, non-preemption, and failover term changes;
- stale-node expiration;
- shared queue and cluster state;
- configuration and timing validation;
- six-task idempotent submission;
- source-evidence tamper rejection;
- lease expiry and redistribution;
- exactly one terminal success;
- final distributed Chief Engineer approval;
- immutable execution IDs;
- internal Docker networking;
- loopback-only published ports;
- read-only mounts;
- non-root containers;
- forced-crash and cleanup behavior;
- absence of cloud/provider credentials in the cluster runtime.

## Security boundary

The simulation uses defense in depth:

- TLS 1.2 or newer for inter-node traffic;
- CA and hostname verification;
- HMAC-SHA256 request authentication;
- bounded request body size;
- timestamp replay window;
- internal Docker network with no runtime egress requirement;
- non-root containers;
- read-only root filesystem;
- dropped Linux capabilities;
- `no-new-privileges`;
- read-only evidence and credential mounts;
- external runtime-only secrets;
- source path containment and SHA-256 verification;
- bounded task attempts and dead-letter handling.

The unauthenticated `/healthz` endpoint returns only minimal node health and leader identity. All cluster-control endpoints require HMAC authentication over TLS.

## Production boundary

Phase 24A uses the isolated Compose project `aionex-phase24a` and network `aionex-phase24a-internal`.

It does not modify:

- the production Compose project;
- production containers;
- databases;
- Redis;
- Nginx;
- Cloudflare Tunnel;
- production environment files;
- production networks;
- public or private domains.

The Phase 24A containers and network were removed after the simulation. Production remained running and healthy.

## Next phase

Phase 24B will move the proven design from three containers on one server to real nodes on separate hosts. It must add host identity, cross-host TLS certificate lifecycle, durable shared-state placement, host-level failure testing, network partition handling, and controlled production-adjacent deployment without changing the current production boundary until approval.
