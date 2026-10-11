# FR09H — 5,000 genuinely active authenticated users acceptance profile

**Owner scope:** AIONEX AIOS only; NEW server `nc-ph-4354`. A complete FR08E operational multi-project/conversation acceptance must precede a genuine FR09 mixed-traffic run. The historical `docs/project/PLAN.json` FR09 baseline remains **1,000 users**, and no 1,000-user partial success can be renamed as 5,000-user acceptance. This additive profile explicitly targets **5,000 active authenticated users**, at least **15,000 projects, 15,000 conversations and 15,000 durable jobs**, with 15 minutes at full occupancy. It does not claim 5,000 simultaneous paid/GPU inference jobs on a single CPU host.

Profile file: `docs/project/capacity/FR-09H-5000-MIXED-PROFILE.json`. It is compatible with the existing `scripts/capacity/fr09_profile.py --plan` reader without relaxing any original SLO, isolation or safety thresholds. The profile defaults to `status=NOT_RUN_OR_ACCEPTED`.

## Actual observation and admission (2026-10-11 14:49 UTC)

Independent read-only `statvfs` measurement on NEW proved `/var/lib/docker` and `/var/lib/containerd` are the **same dedicated LUKS2/ext4 runtime device**, distinct from the host's 3TiB-free root. Actual free runtime **22.72GiB**, which is **17.28GiB below** the explicit **>=40GiB free** preflight. FR08E has not achieved independent accepted deployment/release either. A root0600 evidence receipt `/var/lib/aionex-migration/r1-management-20261008/FR09-ACTUAL-FS-PREFLIGHT-20261011T144917Z.json` SHA256 `fdc65a2073bcc0798d9dae06c0fef097a12624d94437059b22475206c2ada07e` records admission `heavy_work_permitted=false` and `load_test_started=false` for the canonical 1,000-user baseline.

**Do NOT:** interpret root free space as sufficient encrypted runtime capacity; change or expand live LUKS2 while Docker/PG are running without a reviewed maintenance/rollback operation; prune production images/volumes; replay paid provider actions; weaken FR08, 40GiB minimum or strict SLO; launch 5,000 clients against production; or mark a synthetic unit test as end-to-end capacity proof.

## Intended independent acceptance once admitted

1. Provision an independently secured disposable environment with dedicated encrypted Docker+containerd runtime **at least 40GiB free after image/staging setup**, using approved production-identical image SHA, isolated synthetic accounts and no production provider secrets.
2. Finish and independently sign off FR08E: multi-user/tenant/project/conversation source-release equivalence, Owner policy limits/changes, fair worker dispatch, waiting, reconnect and durable no-replay, using real HTTP and WebSocket, not mocked green flags.
3. Start explicit ramp 25→100→250→500→5,000 authenticated active clients; require 15 minutes at 5,000 with minimum 15,000 projects, conversations and durable jobs. Record genuine completed HTTP/WebSocket results and count lost/disconnected clients, not just seeded DB rows.
4. Independently collect p50/p95/p99, <=500ms ordinary read p95, <=1000ms durable enqueue p95, <=0.5% unexpected errors, zero tenant leaks, lost jobs or duplicate terminal executions, and real failover/reconnection of a worker with fair scheduling.
5. Retain independently verifiable test generator and backend SHA, exact evidence, profile, SLO measurements, rollback and cleanup receipt. An independent reviewer must approve or reject FR09H. A profile file or protected green CI is **source acceptance only**, not live load acceptance.

Both original `PLAN.json` and this new 5,000 profile remain separate; do not silently change the meaning of the original 1,000-user FR09 profile. 
