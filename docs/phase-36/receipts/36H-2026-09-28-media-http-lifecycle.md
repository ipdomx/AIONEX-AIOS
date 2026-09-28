# Phase36 36H — Media file request lifecycle fence

Date: 2026-09-28
Related batch: FR-06C5D10D; FR-07 remains completed.

The three existing media API routers now apply independent maintenance admission
before multipart/body parsing and retain it through response and cleanup.
Exactly eleven file-bearing handlers are enumerated; no public route is added.
Subject rights, provider authorization, tenant scope and token contracts remain.

Real isolated PostgreSQL and ASGI acceptance passed62 cases, including cancellation,
actual storage-thread completion, request streaming and file-response ordering.
The unchanged baseline's44 failures and first patch's four name-registry failures
are retained. No paid/public provider or production customer data was used.

See `docs/project/receipts/FR-06C5D10D-media-http-lifecycle.md` and canonical runtime
evidence for executed results and remaining boundaries. Not a host-cutover receipt.
