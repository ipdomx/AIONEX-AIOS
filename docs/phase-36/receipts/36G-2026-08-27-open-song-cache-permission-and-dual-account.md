# Phase 36G — Open Song cache permission fix and dual-account preparation (2026-08-27)

Status: source/local-runtime validation only; final funded RunPod acceptance remains pending.

## Root cause of the first funded RunPod job failure

- The first funded Open Song RunPod job progressed through queue, worker initialization, and running, then terminated failed with no automatic retry.
- A local startup probe against the same hardened image reproduced the pre-generation failure without creating a provider job or spending provider balance.
- ACE-Step API startup attempted to create its runtime cache under `/app/.cache/acestep` while the AIONEX image correctly ran as the non-root `aionex-song` user.
- The previous image kept `/app` root-owned and had not provisioned that exact cache subtree writable, so ACE-Step raised `PermissionError: [Errno 13] Permission denied: '/app/.cache'` during application startup.

## Least-privilege remediation

- `/app`, `/app/checkpoints`, handler source, and the baked Demucs/model assets remain root-owned and non-writable by the runtime user.
- Only `/app/.cache/acestep` is created as `aionex-song:aionex-song` mode `0700` for ACE-Step's local disk cache.
- Ephemeral ACE-Step temp, Triton, TorchInductor, Hugging Face, XDG, and Matplotlib cache paths are explicitly redirected below `/tmp/aionex-open-song` and created mode `0700` for the runtime user.
- Docker build assertions fail closed unless the ACE-Step cache and temp root have exact ownership/mode and `/app/checkpoints` remains `root:root`.
- A no-provider/no-GPU local startup probe with model eager loading disabled reached `Application startup complete` and stayed alive until the bounded diagnostic timeout. The previous `/app/.cache` permission failure was not reproduced.

## Dual RunPod account / worker preparation

- A second `audio-song-worker-secondary` production Compose profile is prepared with a distinct worker ID and a distinct server-side secret file path. It remains hard-disabled by default.
- The secondary worker shares the durable media store and database authority but does not share credentials with the primary worker.
- Durable claim selection now supports an exact `endpoint_id_sha256` filter. Each live worker passes its own endpoint hash before claiming work, preventing a worker from claiming an execution pinned to another RunPod account/endpoint.
- Existing callers remain backward compatible when no endpoint filter is supplied.
- Automatic resubmission after an ambiguous provider submission remains forbidden and `max_attempts=1` is unchanged.
- The secondary account is prepared but not armed because the server currently contains one unique RunPod API credential. A second key must be stored server-side before the secondary profile can be activated; no credential should be placed in Git or chat.

## Validation

- Open Song handler/source tests: 14 passed.
- Worker/runtime/Compose tests against disposable PostgreSQL 18 migrated through `20260825_0043`: 51 passed, 1 skipped.
- Endpoint-isolation regression verifies the wrong endpoint hash cannot claim a queued execution and does not increment its attempt count; the correct endpoint hash can then claim it normally.
- Ruff on changed Python files: PASS.
- `git diff --check`: PASS.
- Disposable PostgreSQL container and network were removed after testing.
- No new RunPod generation request was made while developing or validating this remediation.
- Production Cloudflare/Tunnel configuration was not changed.
- `.worktrees/` remains intentionally untouched.
