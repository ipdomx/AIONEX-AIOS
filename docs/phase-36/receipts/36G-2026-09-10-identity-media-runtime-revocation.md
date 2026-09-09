# Phase 36G — Identity Media runtime revocation hardening — 2026-09-10

## Checkpoint: isolated regression in progress; production unchanged

Base source: `8d5a805094b3705e5f4f3256e8140c9cce69af5d` (protected PR #602).

The previous session closed fictional Voice Clone and Lip Sync provider acceptance in `36G-2026-09-09-identity-media-provider-input-closeout.md`. Cloudflare R2 DR is already accepted; existing project/multi-project/control-plane capacity evidence is preserved and is not replaced with a new production load test. No Cloudflare/DNS, deferred provider/payment/XR/Namecheap encryption, secondary RunPod, or other project mutation is part of this batch.

## Finding IM-REVOKE-20260910

Source review found that the Super Owner grant/deny decision is checked at request admission but not by the deferred Identity Media worker, the signed provider-input delivery route, or the final user output download route. An admission-time grant can therefore outlive a later Owner deny, user/account suspension, or grant-scope change at a subsequent execution/delivery boundary. This is a discovered enforcement gap, not evidence of an actual unauthorized production request or a compromise.

The earlier governance acceptance covered grant/deny at admission and did not exercise a revoke after enqueue or between the two voice-clone provider stages. This batch adds focused negative regression for those missing boundaries.

## Intended correction and acceptance

- Reuse one current, tenant-bound account/Owner access decision at primary submission, polling, secondary speech submission, provider input delivery, and final output delivery.
- Refresh identity/Owner state instead of trusting the SQLAlchemy identity map's earlier access record.
- Deny a not-yet-submitted job without calling the provider. Preserve already-submitted provider job identities and mark the execution `needs_review`; never claim the provider job was cancelled or automatically resubmit it.
- Recheck before dependent provider calls/output publication. Historical outputs remain private and new download requests must pass current authorization; avoid a new presigned output redirect that would bypass that check.
- Preserve licensed-public-figure fail-closed policy, real-person rights requirements, fictional direct access where authorized, max-attempt semantics, private storage and the existing signed-input transport.
- Reproduce the missing enforcement in a standalone no-network container with disposable test settings, then run positive and negative regression/static checks. No production pytest or paid provider canary is required.
- Protected PR/CI/merge is mandatory before deployment; retain exact previous images and a successful backup/R2 restore anchor before any runtime recreation.

## Technology and security review

No dependency, provider model or API version changes are proposed. The current project's installed backend/test image and existing SQLAlchemy/FastAPI patterns are retained. Official guidance reviewed on 2026-09-10: OWASP Authorization Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html (validate authorization on every request; protect static resources); Replicate prediction data retention, https://replicate.com/docs/topics/predictions/data-retention/ (provider-retained data has a separate lifecycle).

Revocation is a boundary check, not time travel: bytes already downloaded and requests already accepted by an external provider cannot be recalled by changing a local grant. This batch does not falsely assert immediate provider-side cancellation or deletion.

## Handoff

`IN_PROGRESS — REPRODUCE_AND_HARDEN_RUNTIME_REVOCATION`. Production remains on the accepted #602 source until protected merge and explicit rollout acceptance. Voice Transform and Face Swap still require their separate runtime implementation/acceptance; they are not silently promoted to live by this security patch.

## Isolated acceptance completed — 2026-09-10

- The five new negative regressions were first run against the unchanged #602 application source: **5 failed**, each at the actual missing provider-submission/polling/secondary-submission/input-delivery/output-delivery authorization boundary. No real provider or production database was used.
- The corrected focused suite passes **46 tests, 0 failed**, including five real PostgreSQL cross-session cases (Owner revoke, exact-subject scope change, user suspension, organization suspension and billing suspension).
- PostgreSQL 16 was created on a private `--internal` Docker network with no published ports and an in-memory data directory. The fresh schema migrated through `20260908_0046`. Both test containers and their exact network were removed after completion; no Production worker was stopped.
- The five PostgreSQL cases retain strong references to the old mapped authorities, commit a change in an independent session, then prove that the still-open reader session observes and enforces the new state. Runtime authorization is asserted read-only and forbidden from calling billing catalog synchronization.
- Focused Ruff: PASS. Mypy: PASS for all three changed application modules. `git diff --check`: PASS.
- Production schema remains `20260908_0046`; active Identity Media jobs were `0` at the pre-change live read-only check.
- Test evidence: `/opt/AIOS/.deployment-backups/identity-revocation-20260910/` (`reproduction.log`, `reproduction.exit`, `postgres-regression.log`, `postgres-regression.exit`).

## Capacity receipt continuity correction

The previously written 2026-09-07 production-capacity receipt existed on PR #586's branch but had not reached `main`. This batch carries that exact receipt unchanged into the current protected change, preserving its measured 1000-client PostgreSQL/Redis control-plane evidence and its explicit distinction from simultaneous Internet audio/video streams. The larger historical project/multi-project acceptance is not invalidated, repeated or silently reclassified. No new production stress test or capacity/Cloudflare mutation is performed.

## Next protected boundary

`SOURCE_VERIFIED — PROTECTED_CI_REQUIRED`. Merge/deployment completion is not asserted by the local test result. Follow the current branch and its PR; deploy only the exact protected merged source after a healthy backup/R2 restore anchor, retain Backend/Identity-worker rollback image IDs, and recheck live health and authorization without paid provider requests.
