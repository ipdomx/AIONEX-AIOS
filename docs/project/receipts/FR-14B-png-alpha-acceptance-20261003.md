# FR-14B PNG alpha acceptance — 2026-10-03

## Scope

This receipt covers only the distinct FR-14-owned PNG alpha structural/coverage acceptance subpart. It does not implement or claim Replicate transport, provider/account availability, background-removal model output quality, source-resolution preservation, live routing, UI integration, or production deployment.

Owned paths changed in this run:

- web-dashboard/backend/app/services/image_raster_validation.py
- web-dashboard/backend/tests/test_fr14b_png_alpha_validation.py
- docs/project/receipts/FR-14B-png-alpha-acceptance-20261003.md

The preserved FR-14 r4 Replicate worktree and its previously denied adapter/commit operations were not modified or replayed.

## Implemented contract

inspect_png_alpha_coverage() now performs dependency-free bounded decoding of 8-bit, non-interlaced RGBA PNG output and fails closed on malformed or structurally meaningless alpha.

The validator:

- verifies PNG signature, IHDR-first ordering, required IDAT/IEND and no trailing bytes;
- verifies CRC for every parsed chunk;
- bounds compressed body size, chunk count, dimensions and total pixel count;
- accepts only 8-bit RGBA with standard compression/filter method and no interlace;
- bounds decompression to the exact expected scanline size;
- reconstructs PNG filters 0 through 4;
- counts fully transparent, fully opaque and partially transparent pixels;
- rejects fully opaque and fully transparent images.

This proves structural alpha coverage only. It does not prove semantic mask/edge quality, absence of halos, correct subject retention, source-resolution preservation, or provider success.

## Test evidence

python3 -m py_compile passed for both the service module and the new FR-14B test file.

A dependency-isolated direct harness executed the new test functions without the repository-wide backend conftest.py and passed 10/10 cases:

- PNG filters 0, 1, 2, 3 and 4;
- mixed transparent/opaque/partial alpha accounting;
- fully opaque rejection;
- fully transparent rejection;
- non-RGBA rejection;
- CRC corruption and truncation rejection;
- pixel-count and compressed-size limit rejection.

git diff --check passed.

A normal backend pytest invocation could not collect the targeted test because the existing host Python environment lacks sqlalchemy, imported by web-dashboard/backend/tests/conftest.py. No package was installed and this environment limitation is not counted as product pass/fail.

## Runtime / provider boundary

No provider credential was read. No Replicate/OpenAI/Gemini/Fireworks request was made. No paid call, customer data access, live service mutation, database operation, deployment, or production change occurred.

The reviewed Replicate background-removal candidate remains only a source candidate until its separate bounded transport, worker binding, account availability and real output acceptance are implemented and verified. Cross-scope live_media/UI/deployment work remains with the coordinator/actual owner.

## Remaining FR-14 work

- bounded background-removal provider transport and worker binding in permitted owned paths;
- real accepted provider-output validation using this alpha contract;
- measured source-resolution preservation and semantic edge/mask quality;
- design/vector and export acceptance gaps;
- long-scene video/subtitle/VFX/output-quality exits;
- protected integration and deployed acceptance after dependencies, including FR-08.
