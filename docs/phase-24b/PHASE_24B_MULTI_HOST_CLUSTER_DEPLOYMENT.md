# Phase 24B — Multi-Host Cluster Deployment Foundation

## Status

Phase 24B implementation and deployment foundation completed successfully on 2026-08-05.

The code now supports remote AIOS agents on separately managed hosts without sharing a SQLite file or filesystem between those agents. Every agent communicates with a dedicated durable control-plane state authority through mutual TLS, unique host certificates, per-host HMAC-SHA256 request signing, timestamp validation, and durable nonce replay protection.

A three-host Docker lab validated the full cross-host protocol and failure path on the current server. The lab is intentionally not represented as proof that three separate physical or virtual servers were activated.

Foundation result:

- execution ID: `phase24b-multi-host-lab`;
- foundation approved: `true`;
- physical-host activation approved: `false`;
- readiness score: `0.95`;
- tasks succeeded: `6/6`;
- recovered tasks after partition: `1`;
- dead letters: `0`;
- initial leader: `host-a`;
- replacement leader: `host-b`;
- partitioned and rejoined host: `host-a`;
- production modified: `false`.

The remaining blocker is external infrastructure only:

`physical-host activation requires at least three separately managed hosts`

## What Phase 24B adds

### Host identity and enrollment

Each host is enrolled before it can register.

Enrollment binds:

- host ID;
- HTTPS service identity;
- capability set;
- deployment host name;
- unique client-certificate SHA-256 fingerprint.

A host cannot change its certificate, service URL, or capabilities after enrollment without a new controlled enrollment. Revoked identities cannot heartbeat, claim tasks, or acquire leadership.

### Mutual TLS and per-host message authentication

The control plane requires a valid client certificate signed by the Phase 24B CA.

Every protected request also includes:

- host identity;
- method and path;
- timestamp;
- unique nonce;
- SHA-256 of the request body;
- per-host HMAC-SHA256 signature.

The control plane verifies:

- CA trust;
- presented certificate fingerprint against enrollment;
- HMAC signature;
- clock-skew limit;
- durable nonce uniqueness.

A captured request cannot be replayed after its nonce has been consumed.

### Remote durable state authority

Agents do not open the cluster database and do not mount a shared state filesystem.

The dedicated control-plane service owns:

- host enrollment and heartbeat state;
- worker registry;
- durable task queue;
- task leases and recovery;
- dead-letter queue;
- idempotency keys;
- leader leases;
- monotonically increasing leader terms;
- fencing tokens;
- audit events;
- replay nonces.

Agents use only the mutual-TLS HTTPS API for shared state operations.

### Leader fencing and failover

Leader election uses durable transactions and returns a new fencing token whenever an expired leader is replaced.

The validated lab observed:

- term 1: `host-a`;
- forced network partition of `host-a`;
- term 2: `host-b`;
- a different fencing token for the replacement leader.

### Network-partition task recovery

`host-a` leased the slow Architecture task and was disconnected from the inter-host network.

After heartbeat and task leases expired:

- the control plane marked the host unavailable;
- the task returned to the durable queue;
- `host-c` claimed it on attempt two;
- exactly one final successful result was accepted;
- `host-a` was reconnected and returned online;
- all six department tasks completed;
- no task entered the dead-letter queue.

## Added implementation

### `src/aios/multi_host_runtime/auth.py`

Provides per-host HMAC authentication, timestamp validation, nonce signing, request-body hashing, and certificate fingerprinting.

### `src/aios/multi_host_runtime/store.py`

Provides durable enrollment, host state, nonce replay protection, leader leases, terms, fencing tokens, audit events, and integration with the Phase 23 execution fabric.

### `src/aios/multi_host_runtime/control_plane.py`

Provides the mutual-TLS control-plane service and authenticated endpoints for:

- host registration;
- heartbeat;
- leader acquisition and renewal;
- task claim;
- task lease renewal;
- task completion;
- task failure;
- cluster status.

The TLS server requires client certificates and returns sanitized errors only.

### `src/aios/multi_host_runtime/client.py`

Provides the CA-verifying, client-certificate-authenticated, per-host HMAC-signed HTTPS client.

### `src/aios/multi_host_runtime/agent.py`

Provides a remote host agent with independent heartbeat, leadership, task polling, task lease renewal, evidence-hash verification, and bounded task execution.

The agent imports no shared state-store implementation and receives no state database path.

### `src/aios/multi_host_runtime/cycle.py`

Provides the six-department multi-host project cycle, immutable runtime evidence, Chief Engineer review, lab-foundation approval, and an explicit separate-host activation gate.

## Deployment assets

### `scripts/phase24b/generate_deployment_bundles.py`

Generates short-lived external deployment material:

- private CA used only during generation;
- control-plane server certificate and key;
- one unique client certificate and key per host;
- one unique HMAC secret per host;
- enrollment manifest containing certificate fingerprints only;
- protected environment files;
- hardened systemd units.

The CA private key is deleted after certificates are issued. Generated credentials remain outside Git.

### `scripts/phase24b/deploy_inventory.py`

Provides an inventory-driven SSH deployment workflow.

Safety properties:

- dry-run by default;
- `--apply` required for remote changes;
- exactly one control plane and three distinct hosts;
- inventory must match the enrollment manifest;
- SSH batch mode;
- strict host-key checking;
- noninteractive `sudo -n`;
- dedicated `/opt/aionex-phase24b`, `/etc/aionex/phase24b`, and `/var/lib/aionex/phase24b` paths;
- no modification to the existing AIOS production Compose project.

### `deploy/phase24b/docker-compose.lab.yml`

Provides the reproducible lab with:

- one control plane;
- three logical hosts;
- unique host credentials;
- internal-only network;
- loopback-only control-plane port;
- read-only container filesystems;
- UID/GID `10001`;
- dropped capabilities;
- `no-new-privileges`;
- read-only evidence and credential mounts.

### `scripts/phase24b/run_multi_host_lab.py`

Builds and validates the lab, injects a network partition, proves leader and task recovery, writes hashed runtime evidence, deletes all temporary credentials, and removes the containers and network.

## Evidence

Runtime evidence is retained outside Git at:

`/var/tmp/aionex-phase24b/evidence/phase24b-multi-host-lab`

The evidence proves:

- three enrolled host identities;
- three unique certificate fingerprints;
- mutual TLS requirement;
- per-host HMAC requirement;
- durable replay-nonce protection;
- remote state API usage;
- no shared agent state filesystem;
- leader failover;
- network partition injection and healing;
- task lease recovery;
- six successful department tasks;
- zero dead letters;
- no cloud request;
- no provider-key use;
- no fallback;
- no production modification.

Generated lab credentials were deleted after validation. Containers and the temporary lab network were also removed.

## Tests

Phase 24B tests:

- `19 passed`.

Combined controlled Phase 22C through Phase 24B regression boundary:

- `170 passed`.

Coverage includes:

- HMAC signing and tamper rejection;
- stale request rejection;
- nonce replay rejection;
- enrollment and certificate binding;
- host revocation boundary;
- leader fencing-token rotation;
- stale-host expiration;
- leased-task recovery;
- direct control-plane task flow;
- source-evidence tamper rejection;
- immutable evidence output;
- certificate-bundle generation;
- control-plane and agent systemd hardening;
- inventory dry-run behavior;
- internal lab networking;
- non-root and read-only containers;
- absence of production mutation commands.

## Production boundary

Phase 24B did not modify:

- `/opt/AIOS/web-dashboard/docker-compose.production.yml`;
- `/opt/AIOS/web-dashboard/.env.production`;
- Nginx;
- Backend;
- Frontend;
- PostgreSQL;
- Redis;
- Cloudflared;
- production networks;
- public or private domains.

Production remained running and healthy throughout validation.

## External activation gate

Real Phase 24B activation cannot be truthfully completed on one server.

The remaining activation requires:

- one separately managed control-plane host;
- three separately managed agent hosts, or a minimum of three hosts with a documented role topology;
- DNS names or private addresses reachable between those hosts;
- SSH public-key access with strict known-host entries;
- TCP `9443` permitted only between enrolled hosts and the control plane;
- fresh deployment bundles generated immediately before activation.

No paid server was provisioned and no external infrastructure was changed automatically.

## Next action

When additional hosts exist, generate fresh bundles, replace `CONTROL_PLANE_HOST` in each agent environment, validate the dry-run inventory, run the deployment with `--apply`, inject a real host-level network failure, collect separate-host evidence, and rerun finalization with `separate_physical_hosts=true`.
