# FR-09H — Fail-closed measured 5,000-user evidence integrity (2026-10-12)

**Status: source-level verification only; actual sustained 5,000 authenticated concurrent-user workload has NOT been run or accepted.**

## Verified original bug on protected source

The original `scripts/capacity/fr09_evidence_gate.py` from protected main accepted `FULL_MIXED_ACCEPTED` for the published test receipt even after each of these independent internal contradictions (real executable negative checks; no live accounts or providers):
- A `steady_state.errors=150000` claim with global `error_count=0`.
- `http_observation_count=150000` while also claiming 150,000 steady authenticated reads, 15,000 project-create observations, and 15,000 conversation-create observations. These are distinct HTTP route families and require at least **180,000** observations in aggregate.
- 20,000 unique job IDs while the DB claims only 15,000 total jobs.
- 16,000 total jobs while the sum of all enumerated terminal and outstanding job states is only 15,000.

The original fixture's `profile.users=5000` was a **configured target**, not observed 5,000 simultaneous authenticated users. It contained no measured 15-minute steady-state timestamp window independent of overall test elapsed time.

## Source-only corrective contract

The validator now requires all of the following **in addition to, never instead of**, the original PLAN constraints, flags, ramp 25/100/250/500/1000/2500/5000, database counts, p95 ceilings and errors <=0.5%:
- An explicitly measured `steady_state.authenticated_active_users_min >= 5000` and `steady_state.unique_authenticated_users >= 5000` with unique population >= concurrent minimum.
- Independently reported `steady_state.window_start_epoch` and `window_end_epoch` spanning **>=900 seconds**, fully inside the original run start/completed timestamps, with strict chronological order. A 15-minute overall run does not prove a 15-minute simultaneous steady plateau.
- HTTP observation count accounting for distinct steady reads + project create + conversation create request families without double-counting.
- Steady error count a nonnegative integer bounded by steady requests **and** the actual global error count, which itself cannot exceed HTTP observations.
- All enumerated job statuses sum exactly to the reported DB total, and the number of unique job IDs exactly matches that total.
- Actual DB assets/jobs cannot fall below their declared test-profile target counts.

Each missing, malformed, internally inconsistent or boolean-as-integer observation causes `HOLD_FULL_MIXED` (CLI exit 2), not an acceptance. The optional sharded-read envelope remains independent and can never override failed or missing full mixed evidence. The original test fixture was extended *only to demonstrate the new required schema*: it is synthetic, not a report of any performed workload.

## Independent verification

Source baseline Git blobs: validator `032bd42ffaa1cc6d5a6194ecaa48ce679c96b5ab`; tests `b4e21e333518b3674930b8f868b8056c1dbbeb6d`. The four contradictory synthetic reports each initially returned `FULL_MIXED_ACCEPTED` in isolated NEW-host execution before the patch. After the change, the unchanged original cases plus new 12 regression cases passed **29/29**, Python syntax PASS, no live API calls. Additional negative tests cover missing/low authenticated concurrency, insufficient measured plateau, out-of-run timestamps, malformed numeric types, and real CLI exit-code semantics. The source checker cannot cryptographically attest that a separately produced test receipt is genuine; the generator/run-source-image provenance, independently observed workload and audit trail remain mandatory.

## Isolated capacity lab observation — NOT an acceptance run

The existing **separate**, encrypted LUKS2/ext4 FR-09 lab root `/mnt/aionex/fr09-isolated-lab-20261011` was observed with **119.14 GiB free / 125.42 GiB total** at this inspection, well above the stated 40 GiB scratch minimum. The already-existing socket `unix:///run/aionex-fr09-lab/docker.sock` responds to a read-only `docker info` query with Docker root `/mnt/aionex/fr09-isolated-lab-20261011/docker-data`; production Docker independently uses `/var/lib/docker`. Existing FR09 lab containerd and dockerd were both active. No lab state, unit, filesystem, daemon, image, or production root was modified.

**The verified isolated disk capacity is not proof of measured throughput/5000-user acceptance.** Per the canonical worker admission contract, do NOT launch the heavyweight real workload until complete FR08E integration, per-user isolation and worker/provider acceptance prerequisites are separately met. Preserve no spend/external-provider-inference, source/image hash evidence, Owner-policy denial accounting, full SLOs, durable job uniqueness and rollback/cleanup. This patch does not promote FR09 canonical `merged` source state into `accepted`, and final release remains `FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED`.
