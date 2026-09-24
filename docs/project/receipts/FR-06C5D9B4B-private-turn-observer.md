# FR-06C5D9B4B — Private Coturn observation, isolated implementation

Base: accepted main `9439a7f0520f38fb4c0ed6f966729f1bd3ccdc06` (PR761). This independent host-side reader does not require importing the pending PR762 backend correction. PR762 must nevertheless be accepted before any backend integration or production rollout. The source part of the parent plan remains D9B4; this receipt does not close the parent or replace the canonical runtime journal.

## Actual implemented behavior

`scripts/security/fr06_turn_private_observer.py` is a standard-library-only, read-only host executable. Its caller supplies the exact complete expected container ID set, bounded to four instances. It compares that set before and after both fresh scrapes with all containers bearing the exact approved Compose project/service labels. Empty sets, omitted/added/stopped containers, reused PIDs, changed restart counters, changed image IDs, and shared network namespaces are refused.

Only the pinned Coturn image is accepted. Container ID, image ID, PID start ticks, host boot ID, Docker start time/restart count, network-namespace inode, and the daemon-owned listening socket inode are retained in the observation. The exporter must listen on the exact IPv4 loopback address at port 9641, belong to the `turnserver` PID, and have no host port publication. Host/shared-container networking, wildcard listeners, unrelated socket owners and unexpected entrypoints are refused. No daemon configuration, environment, command line, user identity or secret is returned.

The reader holds the selected network namespace descriptor during a bounded `nsenter`/isolated Python child. It performs only an HTTP GET to fixed `127.0.0.1:9641/metrics`; there is no arbitrary URL, proxy, redirect or compressed-response support. Only parsed aggregate counts leave that namespace. The payload is capped at one MiB; individual commands are limited to five seconds and the observation interval is bounded. Cancellation/failure does not cause a retry, service action, admission transition or allocation cleanup.

The parser requires the exact gauge type and one finite nonnegative integral series per required relay transport. Missing metrics or transport series, malformed labels/counts, duplicate series, unexpected transport profiles, timestamps, noncanonical data, oversize or truncated input fail unavailable. A missing metric is never converted into zero. Both UDP and TCP relay types are required by default. Narrowing is supported only through explicit inspected `--no-tcp-relay` / `--no-udp-relay` flags; a disabled relay configured solely in a file is not inferred by reading secrets and can conservatively remain UNKNOWN.

## Executed tests, not source-text assertions alone

The local executable unit suite contains 112 passing cases. The complete root suite passed 2,135 tests, with no failures or skips; Ruff and Mypy also passed for the new reader. It covers gauge parsing, malformed/missing/duplicate input, transport completeness, counts and privacy, exact multi-instance coverage, process/boot/network/socket/image changes, late fleet changes, command deadlines, daemon socket ownership, wildcard/IPv6 listeners, project isolation, metadata policy, transport failures, and non-exact HTTP responses.

Real disposable Coturn tests used the pinned image with `--network none`, the metrics listener on container loopback only, synthetic fixture credentials and no production mounts. Both a UDP-only profile and a combined UDP/TCP profile were exercised with `turnutils_uclient`. The executable host reader observed positive allocation counts, then two explicit zero-count samples before daemon shutdown, while the process epoch remained unchanged. Cold-start absence of the allocation series returned UNKNOWN. UDP and TCP clients exited successfully. Specifically owned test containers were removed.

The lab used a short eight-second allocation lifetime to keep acceptance bounded; this is a TEST configuration, not the current production lifetime and not a production drain result. Initial setup failures (a missing JSON closing brace in the Docker formatting template and the image executable requiring NET_BIND_SERVICE in the capability bounding set) are retained in the runtime evidence, corrected, and followed by successful reruns. They are not described as earlier successful tests.

Runtime logs, exact samples, JUnit results, runnable lab scripts and a hash manifest are retained under `/opt/AIOS/docs/project/runtime/d9b4b-private-turn-observer-20260924/`. They are mutable runtime evidence, not committed as application assets.

## Deliberately unclaimed

This is a two-point observation of the exact inspected Coturn instances, not proof of global fleet discovery, a quiescent interval, expired credentials, closed maintenance authority, completed provider jobs or filesystem-writer drain. It does not enable Prometheus, alter public ports, read application secrets, contact production Coturn/LiveKit, migrate 0064, or restart production services. All rollout/provider/full-host authority flags stay false. Integration must bind this observation to fresh before/after closed maintenance authority, credential closure, a vetted instance/relay profile and independent production acceptance.

The previous limitation is deployment visibility, not a claim that Coturn cannot be measured. The pinned image was tested directly. Upstream reference material: `https://github.com/coturn/coturn/blob/master/src/apps/relay/prom_server.c` and `https://github.com/coturn/coturn/blob/master/examples/etc/turnserver.conf`; these are descriptive references, not substitutes for pinned-image evidence. The current wiki declares itself outdated.
