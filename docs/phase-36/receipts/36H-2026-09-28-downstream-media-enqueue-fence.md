# Phase 36H — Downstream media queue-publication maintenance fence

FR-06C5D10C adds a shared-transaction maintenance check before eight media arm
methods, media graph creation/revision and the 3D create-job request handler.
Existing cost/consent, tenant scope and provider checks remain unchanged.

The corrected baseline reproduced46 failures in54 real PostgreSQL cases; the
same54 cases pass after correction. Expanded58 cases and combined377 media/3D/
graph/live-API regressions pass without failures or skips. Provider and upload
boundary doubles are explicit; no live provider request or customer data is used.

Reference: `docs/project/receipts/FR-06C5D10C-downstream-media-enqueue-fence.md`.
This is source and isolated-test evidence only. It does not certify deployment,
provider drain, full-host closure, FR-06 completion or final platform release.
D10B worker-cycle changes and completed FR-07 remain independent.
