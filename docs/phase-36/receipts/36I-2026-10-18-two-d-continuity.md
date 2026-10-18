# Phase 36I — 2D runtime continuity acceptance

Date: 2026-10-18 UTC
Scope: FR16B generated 2d-animation and 2d-game runtime continuity.

## Problem and change

The generated animation stopped scheduling frames after frame 240. The generated
game stopped after frame 300. Keyboard events could still change the game's
closure after that point, but its canvas and published evidence stopped updating.

This change removes only the two frame-count conditions around
requestAnimationFrame. Each runtime continues to schedule one next frame. The
builder API, artifact verification, keyboard controls, HTML, game manifest, and
offline/no-provider contract remain unchanged.

The August 25 acceptance receipt remains historical evidence for its original
source and short browser/video run. It does not establish sustained playback for
the changed source. This receipt records a new execution against the exact source
below.

## Exact source and generated artifacts

| Artifact | SHA-256 |
| --- | --- |
| Baseline src/aios/three_d_web/two_d.py (7,173 bytes) | f992d00c15ca37d0a8156891be2e47b145a0d5e90494f424214ffe35af82241b |
| Accepted src/aios/three_d_web/two_d.py (7,146 bytes) | 9614a1862e93b79980131c5ee213e39d0457e81018cb74fb176b886f64d07e48 |
| Baseline animation.js | 085a9db7546349f6a9cbcb4c126261f1fccde24640c00974eb50e8c9fe91f0cb |
| Baseline game.js | f81254dd6e8ca5e26ea1548f861063ad842e946611c2560cb5e317ca630b79a6 |
| Accepted animation.js (479 bytes) | 1da07c5b8bfef9249e69fcf198171e2ad557b96decdbfa487a935ec829db0d4d |
| Accepted game.js (708 bytes) | 6aac8055edef8bb8829ef3565445b5a7bd87c9e68c26d9f5aad424b6853d1c1c |
| Accepted build manifest | 9278624059fe3c25b458ab7219c57a7f7cb37b9cc086347b0530f3103aab64ef |

## Actual Chromium execution

Runtime: Playwright 1.62.1, Chromium 151.0.7922.34, sandbox enabled.
Artifacts were built from each pinned source in a separate input directory.
The harness verified manifest and artifact hashes before opening the pages.

Baseline execution: 2026-10-18T11:20:34.832Z to 11:20:45.862Z.
Result: REGRESSION_REPRODUCED.

| Baseline case | Frames before / after observation | Observed result |
| --- | --- | --- |
| Desktop 2d-animation | 240 / 240 | Canvas stayed identical and x remained 220. |
| Desktop 2d-game | 300 / 300 | After ArrowRight and Space, the canvas and published x=80, score=0 stayed unchanged. |

Candidate execution: 2026-10-18T11:22:00.286Z to 11:22:29.745Z.
Result: PASS, all four required cases.

| Candidate case | Viewport | Frames before / after observation | Observed result |
| --- | --- | --- | --- |
| 2d-animation | 1440 x 900 | 360 / 391 | x changed from 40 to 133; canvas pixels changed. |
| 2d-game | 1440 x 900 | 420 / 451 | Late ArrowRight and Space changed x from 80 to 92 and score from 0 to 1; pixels changed. ArrowLeft subsequently restored x=80. |
| 2d-animation | 390 x 844 | 360 / 390 | x changed from 40 to 130; canvas pixels changed. |
| 2d-game | 390 x 844 | 420 / 451 | The same late keyboard input updated x, score, and canvas; ArrowLeft restored x=80. |

The observations began after the old 240/300 frame limits. The two game cases
used keyboard input at both viewport sizes. This is not touch-device acceptance.
All six baseline/candidate cases recorded zero external requests, console errors,
page errors, and failed requests. Before/after canvas and viewport PNGs accompany
the machine-readable results.

## Execution boundary and evidence

Execution used the existing encrypted isolated lab and its cached Playwright
image. Containers had no network, no production mounts, no Docker socket mount,
a read-only root filesystem, UID/GID 65534, no capabilities, no-new-privileges,
active seccomp, and docker-default AppArmor in enforce mode. Chromium retained
its sandbox. The containers were removed after completion; the lab had no
remaining containers.

The first wrapper version refused its own pre-start AppArmor assertion before
browser execution and removed the created container. That failed admission is
retained. Version 2 explicitly configures the profile, verifies it in the running
process before Node execution, and verifies it again after completion. The actual
runtime enforcement checks passed. This was a harness lifecycle correction.

Private evidence is retained under:
`/var/lib/aionex-migration/r1-management-20261008/CONTINUATION-20261018T1040Z`.

| Evidence | SHA-256 |
| --- | --- |
| Browser harness accept_continuity.mjs | 6bf55132289bf9541433d968c22f52578a80631c9b31de4a65b26f3beca35195 |
| Executed container wrapper v2 | 51a7e8a873a7049cbaff6107dfc4391568cc7117e8d8009a60f2d86585d96636 |
| FR16B-BASELINE-RESULT.json | 05768391670576eb0f74bd960d2a7a1d63bdcbcd4d26544762aa0aac55e5a582 |
| Baseline browser-continuity.json | de65f4206aec84384ef3436d61309a434bd606cf952ec2238b48937e73f68232 |
| FR16B-CANDIDATE-RESULT.json | c22279029e03cd9d896f8bd68665d5389d442f5894c7d15b367fee61e574eac9 |
| Candidate browser-continuity.json | a8f7b3ec506d8b8db91d12e272251d4c337ee6881cd2b2333713cba14c9a31b2 |
| FR16B-NODE-REGRESSION/RESULT.json | b3c6cc0df03d31da8fa520f8922a5519fdbdbfc46dedd0772066b6975e8fd2e2 |

Detailed browser receipts and PNGs are in the corresponding output-baseline and
output-candidate directories under:
`/mnt/aionex/fr09-isolated-lab-20261011/fr16b-continuity-20261018`.

## Regression protection and acceptance scope

The added tests build actual artifacts and execute their JavaScript in Node VM
with deterministic animation-frame, canvas, and keyboard adapters. They require
animation playback through frame 650, game playback through frame 604, exactly
one pending callback, visible player movement, and a painted score after late
keyboard input. These executable regression checks supplement the actual
Chromium evidence; they are not additional browser/device acceptance.

Targeted pytest execution on the current-main candidate completed at
2026-10-18T11:35:27Z: 9 passed in 0.94 seconds, with no skips. The host Python
suite used a task-only Node relay into the pinned isolated lab image; it installed
no host dependency and mounted no host files into those Node containers. Both
containers exited and were removed. The Phase 36 reporting check also passed for
the four changed paths.

The current-source guard now binds the exact newly executed source and this
receipt. The historical August receipt and its presence check are preserved.

Accepted: the reproduced frame-limit defect and sustained drawing/input behavior
in these bounded 2D runtime cases.

This receipt does not close the full FR16 gate, asset optimization/compression/LOD,
Hunyuan rebuild/security, nonempty production asset delivery, independent recovery,
XR hardware acceptance, or release acceptance. It performs no provider requests,
production deployment, or production configuration change.
