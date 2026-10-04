# FR-10A synthetic failure-harness preparation — 2026-10-03

Run: `fr10-scheduled-20261003T125012Z-6ac041e2-r10`
Base: `3b382d00bacb1db50bf532d5f085e85585f32006`
Scope: source-only FR-10 N2/F1/M1 preparation; no provider, customer, live DB, service, production, or heavy-load effect.

## Current runtime observations

Read-only review of the current shared worker shows that durable claims are fenced with lease owner/token plus an incrementing fencing generation, claim order prefers lower tenant active count then priority then age, and queue telemetry exposes a global oldest wait plus counts by resource class. The current worker also treats several transport/execution failures as transient and can cancel pending work during bounded shutdown drain. FR-10 does not own those shared runtime files, so this change does not modify them.

The acceptance harness therefore makes the missing safety contract explicit without claiming the runtime is already repaired:

- **N2 ambiguous DB commit:** a lost/unknown durable commit acknowledgement after an external-effect boundary is reconciliation-only and never automatic replay.
- **Provider/network ambiguity:** provider acknowledgement loss after send is reconciliation-only; network loss before an external effect may retry while budget remains.
- **Leases/fencing:** stale generations are rejected.
- **No double send / no double charge:** the synthetic matrix must report zero automatic replays after an effect boundary and zero duplicate-send/duplicate-charge risk.
- **F1 bounded fairness:** queue evidence is collated per resource class with oldest wait and tenant count; classes with no eligible worker are classified as capacity/configuration gaps, not fairness success.
- **M1 resource abort:** a pre-effect resource abort may retry within budget; a post-effect abort is reconciliation-only.
- **Metrics:** deterministic synthetic recovery, queue-wait, throughput, and saturation values are collated without a heavy load.

## Synthetic fixture

The fixture contains nine bounded scenarios: worker loss before effect, stale completion after lease reclaim, provider ACK loss after send, pre-send network loss, DB commit ACK ambiguity after an external effect, pre-effect DB failure, pre/post-effect resource aborts, and retry-budget exhaustion. It also contains CPU/GPU/unsupported-class fairness samples and a small deterministic metrics sample.

## Verification

- Harness CLI: **PASS**, `accepted=true`, `heavy_or_live_effects=false`.
- Matrix: expected actions all match.
- `automatic_replays_after_effect=0`.
- `duplicate_send_risk=0`.
- `duplicate_charge_risk=0`.
- `stale_completions_accepted=0`.
- Targeted pytest: **7 passed**.
- Python compile: **PASS**.
- Git whitespace check: **PASS** after staging/commit validation.

Synthetic metric sample:
- recovery max / p95: 8.2s / 8.2s
- queue wait p95: 4.0s
- throughput: 24.0 jobs/min
- worker saturation: 0.75

## Remaining dependency boundary

This is isolated source-level FR-10 preparation only. FR-09 is not accepted and FR-08 remains upstream of that acceptance. No 1000-user heavy run, integration, live verification, deployment, or FR-10 final closure is claimed here. Coordinator FR-25 alone may merge, canonical-record, or deploy.
