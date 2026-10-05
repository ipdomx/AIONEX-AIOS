# FR-11B2 — Local media ownership handoff repair — 2026-10-05

## Finding

The first live Voice Transform acceptance request used only synthetic WAV fixtures and was admitted through the governed Identity Media path. The durable execution entered `needs_review` before provider submission. The worker evidence showed `provider_state=not_started` and a local `PermissionError` while reading the private input object.

The shared media vault root is owned by the runtime worker identity (UID/GID 1000:1000), while the Backend container runs as root. `LocalMediaObjectStore.put_bytes()` created nested request directories and files as root-owned `0700/0600`, so the non-root Identity Media worker could not traverse/read them.

No accepted provider job is claimed by this finding, and no automatic replay is authorized.

## Repair

- Record the ownership of the configured local media root.
- Preserve private directory mode `0700` and file mode `0600`.
- When the writer is root, assign newly-created nested directories and temporary object files to the media-root UID/GID before atomic replacement.
- Non-root writers do not perform privileged ownership changes.
- Path traversal protections and atomic replacement remain unchanged.

## Validation

- Added a regression test covering a root writer and a worker-owned media root.
- Added isolated module validation with no network, provider call, production database access or customer data.
- Live retry remains separately gated on deployment plus proof that the prior execution has no provider job identifiers and remains `provider_state=not_started`.

## Boundary

This receipt is source repair evidence only. It does not claim the FR-11 live provider/output acceptance until the repaired image is deployed and one governed synthetic Voice Transform request completes with a verified audio output and revocation/download checks.
