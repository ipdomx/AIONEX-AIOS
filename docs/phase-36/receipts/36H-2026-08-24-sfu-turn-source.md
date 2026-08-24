# Phase 36H.3 — SFU / signaling / TURN-STUN source receipt

Status: **source candidate only; fail-closed; production untouched**.

## Objective

Create the provider-neutral SFU boundary and a LiveKit/Coturn candidate profile without opening media ports, starting a provider, issuing provider credentials, changing firewall/DNS/tunnel state, or applying realtime database migrations to production.

## Technology refresh — 2026-08-24

Official upstream sources were rechecked at the start of this batch:

- LiveKit Server: `v1.13.5`, Linux/amd64 manifest digest `sha256:d0d1cfdbe95617647bbe91630454526c2cdd88cec83f41114b3495b444918b9a`.
- LiveKit Egress: `v1.13.0`, Linux/amd64 manifest digest `sha256:a3e61a70479694a5075cff3c081ab633f34d3bfa778adc6089935c96908b6550`; Egress remains out of this activation batch.
- Coturn: `4.17.2`, Linux/amd64 manifest digest `sha256:75e9ebd1e19005bec0c7f591d29afe22f959916ac8d9c852452f27db8c789828`. The current release fixes outgoing UDP TTL incorrectly pinned to 1 on client-facing sockets.
- OpenTelemetry Collector: `v0.159.0` remains the current observability reference.
- Grafana k6: package registry exposes `2.2.0`; realtime load certification is reserved for 36H.6 and is not claimed here.

Reference entry points:
- https://github.com/livekit/livekit/releases
- https://github.com/livekit/egress/releases
- https://github.com/coturn/coturn/releases
- https://github.com/open-telemetry/opentelemetry-collector-releases/releases
- https://github.com/grafana/k6/pkgs/container/k6/versions

## Source delivered

- `web-dashboard/backend/app/realtime/sfu.py`: provider-neutral SFU protocol, secure candidate configuration, STUN/TURN validation, opaque tenant/room provider naming, source-only LiveKit adapter.
- `deploy/phase36h/docker-compose.realtime.disabled.yml`: isolated internal-only Compose profile, immutable LiveKit/Coturn image digests, no host ports, help/preflight commands only.
- `deploy/phase36h/kubernetes/realtime-media-disabled.yaml`: two `replicas: 0` candidates, no Service objects, default-deny ingress/egress NetworkPolicy.
- `web-dashboard/backend/tests/test_phase36h_sfu_turn_adapter.py`: fail-closed, secret-reference, identity, image and network-boundary regression tests.

## Security / privacy / tenant boundaries

- API key/secret and TURN credentials are represented only by `env://`, `/run/secrets/`, or Kubernetes secret references; raw secret values are rejected by configuration validation.
- Provider room identities are deterministic hashes of tenant + room identifiers and do not expose raw organization or room identifiers.
- The adapter has no HTTP/network client or LiveKit SDK dependency in 36H.3.
- `provision_room()` fails closed even if the candidate configuration is marked enabled; runtime provider mutation is intentionally deferred to a separate activation gate.
- Recording/Egress is explicitly disabled.
- No production host port, Kubernetes Service, firewall rule, DNS record, tunnel route or external credential is created.

## Not completed

This receipt does **not** claim live SFU/TURN runtime acceptance, provider credential validation, production network reachability, 1:1/group calls, screen share, adaptive bitrate/simulcast/dynacast, Egress/recording, Creative Studio ingestion, 1000-user realtime scale, failover, or recovery certification.
