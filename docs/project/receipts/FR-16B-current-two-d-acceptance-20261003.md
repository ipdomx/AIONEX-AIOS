# FR-16B current 2D source continuity acceptance — 2026-10-03

- Batch: FR-16
- Run: `fr16-scheduled-20261003T063410Z-6ac00293-r9`
- Task: `6ac00293fd888191bc8627f251731318`
- Base source: `1466516d4ce4d78290f34050ba832036c85c2655`
- Policy SHA-256: `1a5ade124dfcdab55e28344424cae91996ee141e8783fcb0397fc4667de6fc04`
- Coordination helper SHA-256: `020e29cd84f5ecc9abb5aa8456b59721687cfa89f3d6e4cde97d128d3b6bf2a5`

## What this subpart proves

The current `src/aios/three_d_web/two_d.py` blob is byte-identical to the implementation historically exercised by the accepted real-browser evidence in `docs/phase-36/receipts/36I-2026-08-25-two-d-runtime.md`. Its SHA-256 is `f992d00c15ca37d0a8156891be2e47b145a0d5e90494f424214ffe35af82241b`, and the last commit touching that path remains `0c4bf553285ba39079bbf4831009995e575c1505`, which is an ancestor of this run's base.

The historical receipt records real headless Chromium execution for the 2D animation/game path and a WebM preview. This run does **not** relabel that historical browser execution as a fresh browser run. Instead it proves current-source continuity to that real execution evidence and adds a tracked FR-16-specific acceptance guard.

## Test evidence

Executed in this run's isolated FR-16 worktree:

`pytest -q tests/test_fr16b_current_two_d_acceptance.py`

Result: **2 passed**.

The acceptance test verifies:
1. the current `two_d.py` exact SHA-256;
2. the last source commit for `two_d.py` is the historically executed accepted commit and remains in current ancestry;
3. the historical real-browser receipt is present and explicitly references Chromium, `2d-animation`, `2d-game`, and WebM evidence.

## Boundaries

- No application source was modified in FR-16B; only this acceptance test and receipt are new.
- No GPU job, Hunyuan image build/activation, provider call, paid request, live service, DB, key, mount, swap, tmp, XR, MCP/root/settings, or production effect occurred.
- Hunyuan remains quarantined and fail-closed.
- The old refused FR-16A staged receipt/worktree was not edited, retried, amended, committed, or published.
- This is **FR-16B current-source acceptance evidence**, not final FR-16 operational closure. FR-16C current 3D storage/worker hardening acceptance, FR-16D safe Hunyuan rebuild/security/functional acceptance, and FR-16E deployed asset acceptance remain open.
