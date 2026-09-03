# Phase 36N — External-gate reporting closeout — 2026-09-03

## Purpose

The final integrated runtime closeout proved that Phase 36 has no active internal execution backlog while batches 36G, 36H and 36I still contain capabilities that truthfully require external rights, provider, network or device acceptance. An older unmerged branch (#490) proposed useful reporting metadata but also contained August capability definitions that are now stale and would downgrade newer runtime evidence if merged directly.

## Additive reporting contract

`phase36_program_snapshot()` now reports, without changing any capability maturity or batch status:

- `external_gate_batches` at the program level;
- `local_closeout_complete` per batch;
- `blocking_external_gates` per external-gate batch;
- `unresolved_capabilities` per external-gate batch;
- `ungated_unresolved_capabilities` per external-gate batch.

For an `external_gate` batch, local closeout is true only when every capability below `runtime_verified` has at least one explicit external gate. Complete batches remain locally closed without being reclassified by the maturity ladder.

## Current invariant

The authoritative current registry remains newer than PR #490. In particular, current 36G evidence includes later broad-audio, funded-music and open-song receipts from 2026-08-26/27. No maturity or provider status is reverted by this change.

Current external-gate batches are `36G`, `36H` and `36I`. Each has zero `ungated_unresolved_capabilities`. This means the repository can distinguish a truthful external dependency from unfinished local engineering without claiming that the externally gated capability itself is complete.

## Safety

This is reporting metadata only. It does not enable Project AI, media generation, paid provider calls, Hunyuan, realtime egress, advertising spend or any external credential. No production data migration is required.
