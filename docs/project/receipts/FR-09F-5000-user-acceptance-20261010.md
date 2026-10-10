# FR-09F — Owner-approved 5,000 concurrent-user full acceptance (2026-10-10)

**Status: acceptance TARGET amended, NOT yet performance-certified or deployed.** This supersedes the old 1,000-user target for future release acceptance; historical test records remain unchanged and must not be reclassified as 5,000-user PASS.

## Exact operating target

- **5,000 authenticated active users** tested as concurrent application participants, with **15,000 isolated projects**, **15,000 conversations**, and **15,000 durable background jobs** at minimum (three of each per simulated user as the capacity profile; not a permanent product quota).
- Authenticated API project and conversation create/list/read; tenancy isolation; owner message/time/project limits under concurrent policy changes; durable enqueue/claim/terminal; no lost jobs, duplicate terminal executions, or cross-tenant reads/writes. Cover read and write routes, not synthetic GET alone.
- Incrementally ramp **25 → 100 → 250 → 500 → 1,000 → 2,500 → 5,000**. After reaching 5,000 maintain **at least 15 minutes** of representative mixed activity and capture complete per-route P50/P95/P99, request count, http status/timeout/connection errors, enqueue and queue-age percentiles, database waits, Redis, process CPU/memory, and storage.
- Preserve all existing acceptance limits: **read P95 ≤500 ms**, **durable enqueue P95 ≤1,000 ms**, **unexpected errors ≤0.5%**, **zero** tenant leaks, lost jobs, and duplicate terminal executions. Count legitimate policy denial separately with independent evidence; don't hide actual server errors or exclude failed requests from denominators.
- Real simultaneous heavy AI/GPU requests have separate measured admission ceilings and provider/license constraints. **5,000 signed-in users does not mean 5,000 concurrent heavy model generations** on one 64-logical-CPU machine.

## Isolation and failure stops

- Do not load-test public production, reuse the live PG/Redis/customer projects, or use production API secrets. Prepare a **separate, short-lived** test backend+PostgreSQL+Redis, synthetic tenants, isolated network, independent DB/volumes, no outward provider, billing, RunPod or customer calls. Identify all image/volume/port bindings before starting anything.
- Preserve 36 running production containers, Cloudflare, root secrets and real customer jobs. Reserve substantial CPU/memory and disk headroom; new host field audit Oct 10 observed **64 logical CPUs**, about **128 GiB RAM**, roughly **3.0 TB** root filesystem free, but Docker runtime vault had only **~23 GiB free**. These are point observations, **not** a load admission guarantee.
- Stage gate failures, unplanned provider calls, CPU/memory pressure, Docker-runtime free space, unexpected errors, tenant leakage or live readiness regression must immediately abort the test; keep an immutable failure receipt and clean up *only identifiable disposable test resources* after evidence is secured.
- No `docker compose up` or equivalent 5,000-user test is authorized solely because this document exists; first verify an independently isolated test environment and safe resource envelope. Stop for any tool/platform refusal; no alternate tool/path/worker to bypass it.

## Historical evidence — must not be overwritten

- Oct 5 full 1,000-user mixed harness receipt: **FAIL** with 21,896 errors and authenticated-read P95 2,759 ms; project and conversation API creation timing coverage absent.
- Oct 5 separate four-shard 1,000-user **read-only** test: 30,000 reads over 15 minutes, no errors, max shard P95 17.135 ms; **PASS for reads only**.
- Oct 5 NS-13 synthetic 2,500/5,000 **read-only** staged envelope: 5,000 sampled, 15,000 GET requests, no errors, max shard P95 about 20.97 ms; not a complete 5,000-user mixed acceptance.
- On Oct 10 owner explicitly corrected the target to **5,000 full users** because the new server was purchased for that scale.

## Source acceptance and reproducibility

The updated `docs/project/PLAN.json` is authoritative for the forward target. `scripts/capacity/fr09_profile.py` validates the full 5,000-user ramp and at least 15,000 jobs. `scripts/capacity/fr09_evidence_gate.py` and offline negative tests must fail closed against stale 1,000-user or status-only reports, and may only classify the full mixed run once genuinely measured data fulfills every gate.

**Not complete until:** independent 5,000-user representative test receipts (including 15 minutes mixed activity), exact source/image hashes, actual pre/post production readiness, tenant and owner-policy negative tests, no-provider-spend proof, safe rollback/cleanup evidence and reviewed release approval. A passing unit test or a fabricated fixture is not this proof.
