# FR-09E — fail-closed mixed 1,000-user evidence gate

**Status: SOURCE PROPOSAL ONLY, NOT production capacity acceptance.** No live traffic, service, secret, provider or customer data is used by this evaluator.

The current FR-09 profile requires 1,000 authenticated active users, 3,000 distinct projects and conversations, 3,000 durable jobs, 15 minutes steady operation, ordinary read P95 ≤500 ms, durable enqueue P95 ≤1,000 ms, unexpected error rate ≤0.5%, and zero lost/duplicated jobs or cross-tenant leaks. The read-only sharded envelope is an additional useful SLO test, **not a substitute** for full mixed workload acceptance.

Evidence observed on NEW (Oct 5, 2026):

- FR09-EXPANDED-CAPACITY-20261005.json: **FAIL**. 1,000 synthetic users/3,000 seeded projects, conversations and jobs, 21,896 errors, authenticated-read P95=2,759.047 ms. Project and conversation API creation timings were not exercised (zero measured), so the full application journey cannot be promoted as proven.
- evidence/FR09-EXACT-MERGED-15M-20261005.json: **PASS** for a **different** read-only envelope, 1,000 synthetic sharded readers/30,000 GETs in 15 minutes, zero failures and max shard P95=17.135 ms. The read-only envelope may be recorded as a distinct subgate.
- evidence/NS13-CAPACITY-GROWTH-20261005.json: PASS on staged 2,500/5,000 synthetic read traffic only, **not** heavy multimodal generation or end-to-end acceptance.

The new scripts/capacity/fr09_evidence_gate.py independently rechecks numeric observations as well as boolean evidence fields, requires the original full-mixed profile, project/conversation API creation timing coverage, confirmed 3,000 completed jobs, and per-tenant isolation. It explicitly cannot promote the read_only subgate into FULL_MIXED_ACCEPTED. Missing or invalid evidence is a hold/nonzero exit.

Offline unit tests use synthetic JSON only, including negative cases where a report falsely claims PASS despite measurable latency, errors, absence of create requests, tenant leaks, provider spending or missing fields. This is an evidence-quality improvement; **it is not a repair of performance capacity**. Actual full mixed-load recovery requires bounded isolated instrumentation and independent operational acceptance. No production load is triggered by running the CLI or tests.

Example against approved *offline* receipt paths:

    python3 scripts/capacity/fr09_evidence_gate.py --mixed /path/to/mixed.json --read-only /path/to/read-only.json

Exit code 0 indicates the full-mixed evidence contract meets its thresholds, 2 means HOLD, 3 means invalid/unreadable evidence. An exit 0 still must not be reported as production acceptance unless the underlying actual load test was performed in a properly isolated representative environment and the release approval gates are satisfied.
