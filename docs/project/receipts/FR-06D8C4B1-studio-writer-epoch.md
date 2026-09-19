# FR-06D8C4B1 — Studio writer epoch

Source-only receipt for proving the current application writer generation of the Production Studio asset volume after the exact closed maintenance transition.

The evaluator requires the closed Studio maintenance snapshot, a later Studio execution snapshot, and the current running Compose inventory. The accepted runtime writer set is exactly `backend` plus `studio-worker`; `backup-worker` is read-only. The one-shot `backup-asset-root-init` remains outside the running writer set.

This receipt does not prove process drain, host-process scanning, backup-cycle drain, filesystem cleanup, production deployment, or full-host closure. Those flags remain false. It performs no container restart/stop, admission mutation, or Studio filesystem mutation.

Local acceptance before commit: 16 focused source tests, Ruff success, and 1815/1815 complete repository tests on an isolated source copy.
