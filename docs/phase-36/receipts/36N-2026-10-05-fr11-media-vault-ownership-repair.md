# Phase 36 — FR-11 media-vault ownership repair — 2026-10-05

Scope: coordinator-owned source repair for `web-dashboard/backend/app/services/media_storage.py` and its focused regression coverage only.

Problem:
- A root-running media writer could create nested local-media directories or temporary/output files as `root:root` inside a vault whose durable owner is non-root.
- That ownership drift could break later reads or writes by the intended media-vault owner.

Change:
- `LocalMediaObjectStore` records the private root owner and reapplies that owner to newly created nested directories and temporary/output files when the writer runs as root.
- Existing path-safety behavior and private modes remain unchanged: directories `0700`, files `0600`.

Validation:
- `git diff --check`: PASS.
- Python compile check: PASS.
- Network-disabled isolated media-storage test: PASS.
- Root-writer bind-mount integration: PASS; root and nested parent retain owner `1000:1000`, directory mode `0700`, output mode `0600`.
- Protected PR checks for Security Baseline, CodeQL, Browser E2E Boundaries and Phase 34E Container Security were green at the time this receipt was added; Final Validation was still running apart from the reporting-invariant failure this receipt addresses.

Boundaries:
- No production mutation.
- No provider request or spend.
- No credential read or rotation.
- No deployment or traffic change.
- No FR-09 expanded-capacity claim and no 1000-user realtime-media claim.
