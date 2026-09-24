# FR-06C5D9B4C — Private, epoch-bound Coturn allocation observer

Core prerequisite: exact PR763 head `2c2a2768de7ff8b36d11961fd70e847931375aa1`, preserved as a shared core rather than a duplicate observer. Integration adds to corrective PR #762 merge `985fa4aa6c05c56356a92f6d848ed46e20c1197e`.
Current execution and merge/deployment status remain in the canonical Project Hub, not this source receipt.

## Implemented observation, not another constant rollout flag

`scripts/security/fr06c5d9_coturn_observer.py` performs a real bounded read of Coturn's allocation gauge inside the exact running TURN container's network namespace. It requires the already-enabled metrics endpoint to be loopback-only and unexposed through host port bindings. It does not enable metrics, alter configuration, restart services, mutate admission, migrate the database, or settle resources.

The observer selects exactly one backend and one realtime-turn service in the AIOS Compose project. It validates the pinned image digest, exact configuration command, non-root service profile, read-only private configuration mount and matching mounted inode. Configuration must predate the current process and remain unchanged. The current deployed non-root ownership is UID/GID 65534, mode 0600; the disposable harness was corrected after an initial root-owned fixture was unreadable by the image's default non-root user. The retained initial failure is not counted as accepted evidence.

Before and after the two samples, the backend's existing validated authority reader must return the same explicitly closed schema-8 operation and generation. Docker container ID, image, PID, start time, restart count, host boot ID, process start ticks and network-namespace inode are revalidated, including after the final database read. The network-namespace descriptor remains pinned while sampling. Process alarms and command/read deadlines bound subprocesses and I/O; no daemon, retry loop or background watcher is installed.

Only validated aggregate counts cross the helper pipe. The shared core from PR763 owns parsing and HTTP reads; this wrapper adds closed-authority/configuration binding and validates the actual deployed UDP-only profile, including the daemon-owned loopback socket. Proxies and redirects are disabled, the response size is bounded by the shared core, and no credentials, raw configuration, usernames, rooms or provider tokens are returned. The supported current deployment profile disables TCP relay; exactly one UDP gauge sample is required. Missing, duplicated, negative, fractional, non-finite, extra-transport or username-labeled samples are unavailable, never zero.

## Executed acceptance

The automated unit/behavioral tests execute parsing, exact authority validation, epoch/config changes, closed-gate denial, interval deadlines and preserved output boundaries. They do not use a real provider.

Separately, the actual CLI was exercised end-to-end against real disposable PostgreSQL authority and the same pinned Coturn image, with a real TURN client. No production configuration or credentials were mounted. An internal Docker network had no host port mappings; metrics were accessed through the pinned loopback namespace. A fresh uninitialized gauge was observed with its TYPE declaration but no allocation samples, and the observer rejected it. Two busy samples reported `[3, 3]`. After the deliberately short test-only 12-second allocation lifetime, two samples reported `[0, 0]`, with the same container/process epoch and the same closed PostgreSQL operation. All owned disposable containers/networks were removed.

Runtime evidence is retained at `docs/project/runtime/d9b4b-coturn-observer-20260924/`: `initial-family-observed.json`, `initial-missing.stdout.json`, `real-busy.stdout.json`, `real-zero-after-expiry.stdout.json`, `e2e-result.json`, and the isolated harness. The initial non-root fixture failure is retained separately.

## Exact limit of the receipt

`allocation_zero_observed` is a bounded physical observation for one pinned UDP-only Coturn process. It does not establish expiry of all issued credentials, durable ledger reconciliation, absence of other LiveKit/Egress/filesystem work, coverage of every producer, or a sustained closed host. Therefore `credential_expiry_verified`, `turn_allocation_drain_verified`, `provider_drain_verified`, `full_host_closure` and `migration_0064_rollout_allowed` remain false.

Production metrics are not enabled by this change. A reviewed, rollback-capable operational activation and a fresh closed-authority observation are still required, then integration with the other drain evidence and the independent 0064 rollout. Do not lower production credential/allocation lifetimes merely to reproduce the short disposable test. Do not expose Prometheus or an administrative endpoint publicly. Unsupported topology or a missing metric must continue to fail closed.
