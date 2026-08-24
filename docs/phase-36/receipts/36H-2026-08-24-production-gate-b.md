# Phase 36H — Production Gate B disabled-runtime preflight

Date: 2026-08-24 UTC

## Scope

Validate the pinned LiveKit/Coturn/Egress runtime images and least-privilege container boundaries without opening a public media port, changing DNS/firewall/tunnel state, issuing a recording request, or starting a production media runtime.

## Gate A prerequisite retained

Production Alembic is `20260824_0041`. The four realtime authority tables exist and were empty immediately after migration. Gate A used a private pre-migration PostgreSQL custom-format backup, verified by `pg_restore -l`, before applying the linear `0039 -> 0040 -> 0041` path. Existing production services remained healthy with zero restarts.

## Gate B evidence

- Pulled and verified the exact Linux/amd64 image digests already pinned by 36H source: LiveKit Server `v1.13.5`, Coturn `4.17.2`, LiveKit Egress `v1.13.0`.
- LiveKit image reports version `1.13.5`; Coturn reports `4.17.2`.
- Disposable preflight used a Docker `internal: true` network, disposable Redis, ephemeral credentials, and zero published host ports.
- Attempt 1 correctly failed only Egress startup because the ephemeral config was root-owned mode `0600` while the image runs as UID `1001`; no production resource was changed. Attempt 2 mounted that ephemeral config as `1001:0` mode `0400` and passed.
- Attempt 2: Redis, LiveKit, Coturn and Egress all remained running; LiveKit HTTP and Egress health were reachable only on the internal bridge; Coturn TCP listener was reachable only on the internal bridge; no host port was published; no provider request or recording request was sent; spend remained `$0.00`.
- Egress retained only `SYS_ADMIN` in addition to `cap_drop: ALL`, matching the upstream Chrome sandbox requirement. LiveKit retained no Linux capabilities. Coturn retained only `NET_BIND_SERVICE`.

## Defect found and fixed

The dormant Coturn Compose candidate used `cap_drop: ["ALL"]`. The pinned Coturn image's `turnserver` cannot exec when `NET_BIND_SERVICE` is removed from the bounding set, even for the source-only help/version preflight. The candidate now keeps `cap_drop: ["ALL"]` and adds only `NET_BIND_SERVICE`; a regression assertion protects this boundary.

## Production activation blockers retained

This receipt does **not** claim live-media production readiness. No dedicated realtime signaling hostname or TURN hostname with trusted TLS is configured, no public media listener is open, no firewall/DNS/tunnel mutation occurred, no public TURN reachability test ran, no SFU browser/media soak ran, and no live Egress recording/failover acceptance ran. The host NIC was observed at 1 Gbps full duplex; current LiveKit production guidance recommends 10 Gbps or faster, so the previously requested 1000-user live-media scale cannot be certified on this host from source/admission tests alone.

The next gate is a separate network/hostname/TLS activation gate. It must remain fail-closed until a concrete public signaling/TURN hostname and certificate path exist and the capacity decision is resolved.
