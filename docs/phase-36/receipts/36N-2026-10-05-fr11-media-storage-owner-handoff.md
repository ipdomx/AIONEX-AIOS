# Phase 36 — FR-11 media ownership handoff repair — 2026-10-05

- Scope: production Identity Media / Voice Transform local-media ownership handoff.
- Finding: the root Backend writer created nested local media inputs as root-owned 0700/0600, while the Identity Media worker runs as UID/GID 1000. The first governed synthetic Voice Transform acceptance therefore failed locally with PermissionError before provider submission and entered needs_review.
- Provider boundary: provider_state remained not_started at the observed failure; no accepted provider job is claimed and no automatic replay is authorized.
- Repair: LocalMediaObjectStore records the configured media-root UID/GID and, only when the writer is root, assigns newly-created nested directories and temporary object files to that owner while preserving directories 0700 and files 0600. Atomic replace and path-escape protections remain unchanged.
- Regression: a focused test covers root-writer ownership inheritance. An isolated no-network module test passed. A host-backed integration probe produced the complete nested path as 0700 uid/gid 1000:1000 and the object as 0600 uid/gid 1000:1000.
- Live acceptance remains open until the repaired image is deployed and a governed synthetic Voice Transform request completes with verified audio output plus download/revocation checks.
