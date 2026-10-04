# FR-22B external-watch contract — 2026-10-03

Run: `fr22-scheduled-20261003T1641Z-6ac04201-r10`
Source base: `aa30bde286bbd403c1b562eecfa996a66ce26c5d`
Scope: isolated FR-22-owned source preparation only.

## Contract implemented

`scripts/monitoring/fr22_external_watch.py` provides a dependency-free off-host
watch state machine for the already-identified public API origin.  It does not
configure a scheduler or notification destination and does not mutate
production.

The contract is deliberately strict:

- the target is an **exact HTTPS origin**; userinfo, paths, query strings,
  fragments and HTTP origins are rejected;
- HTTP redirects are not followed, so a probe cannot silently drift to another
  origin;
- TLS certificate probes explicitly require TLS 1.2 or newer;
- `/health` and `/ready` are evaluated separately so reachability and
  readiness degradation remain distinct;
- heartbeat staleness is calculated from the **actual observation timestamp and
  last confirmed healthy timestamp**, never inferred from a cron expression;
- TLS expiry has warning and critical transitions and a renewal recovery event;
- outage/recovery events are transition-based and deterministic, with stable
  fingerprints for downstream deduplication;
- state persistence is atomic and mode 0600;
- emitted output explicitly states `scheduler_sla_claimed=false`.

## Event vocabulary

The source can emit these transition events:

- `target_unreachable`
- `target_degraded`
- `heartbeat_stale`
- `target_recovered`
- `tls_expiry_warning`
- `tls_expiry_critical`
- `tls_expiry_recovered`

The off-host scheduler and delivery channel remain coordinator-owned.  This
source does not change GitHub Actions, external notification settings, service
configuration, DNS/Cloudflare, databases, providers, keys or live containers.

## Intended observation boundary

The prepared origin is `https://api.vip-e.net`, where prior FR-22 read-only
inventory established that the API health/readiness endpoints are the correct
public monitoring surface.  This receipt does **not** claim that an external
five-minute scheduler or alert-delivery path has been deployed.

## Acceptance tests in this change

`tests/test_fr22_external_watch.py` covers exact-origin validation,
healthy/degraded/unreachable transitions, duplicate suppression, timestamp-based
staleness, measured recovery duration, TLS warning/critical/renewal transitions,
atomic state persistence and fixture-mode output that refuses to claim a
scheduler SLA.

No test performs a live network call.

## Dependency and closure boundary

FR-10 and FR-19 are still not canonically accepted.  Therefore this change is
source preparation for FR-22B only.  It does not perform outage injection,
external alert-delivery acceptance, controlled cleanup, deployment, or FR-22
final closure.  FR-25 coordinator
`6abe498cd0ec8191962f9a6d3e4d3bcc` alone may integrate the off-host
scheduler/delivery path, merge/canonical-record the result and deploy after the
project gates are satisfied.

No rollback evidence was deleted or altered.
