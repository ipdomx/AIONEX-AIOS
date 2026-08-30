# Phase 36G — Open Song dual-account routing

- Receipt ID: `36G-2026-08-31-open-song-dual-account-routing`
- Scope: source-only pre-activation routing for two independently funded RunPod Open Song accounts.
- Production provider submissions in this change: `0`.
- Production GPU spend in this change: `$0.00`.
- Cloudflare/Tunnel/DNS changes: none.

## Existing accepted runtime

The primary Open Song runtime remains the already-accepted immutable image
`sha256:6b6ce10bda3adc378fff230b307ac1ce9f86aaf21d82cd6e1f9c9b9f2a19ea34`.
Acceptance v8 remains authoritative: one provider submission, Full Song plus four
Demucs stems, local mix/master/waveform/export, Studio revision 2, final audio QA
PASS, actual cost `$0.02584`, and zero synthetic DB residue after cleanup.
`production/song-production` therefore remains `runtime_verified`; this change does
not expand its rights/disclosure claim.

## Routing change

The user-facing Open Song API now treats the accepted primary binding as the first
member of an account pool and optionally loads a separately accepted secondary
binding. When only the primary evidence exists, behavior is unchanged.

When two distinct accepted endpoint bindings exist, new executions are pinned
*before provider submission* to the endpoint with the fewest active
`planned/queued/running/rendering` executions. Equal-load ties use a deterministic
SHA-256 rank derived from the request idempotency key and endpoint hash, avoiding a
fixed-primary thundering herd while preserving deterministic routing.

The durable execution stores only the selected endpoint SHA-256. Each secret-bearing
worker can claim/arm only rows whose endpoint hash matches its own credential-bound
endpoint. No execution is moved to a different account after the provider submission
boundary. Existing `max_attempts=1`, `automatic_retry=false`,
`automatic_resubmit=false`, and no-cross-account-resubmit guarantees remain intact.
Raw endpoint IDs and credentials are not returned to users.

## Secondary activation boundary

The Compose service `audio-song-worker-secondary` and its isolated secret mount
`web-dashboard/secrets/RUNPOD_GPU_SECONDARY.env` already exist. At source-validation
time the secondary file is present but its `RUNPOD_API_KEY` and runtime binding are
not provisioned, so the secondary account is **not activated** by this receipt.
The API therefore continues to route only to the accepted primary binding until a
separate secondary Endpoint acceptance writes both secondary binding and acceptance
evidence under the configured secondary evidence root.

No secret is committed to Git. Secondary activation must be performed server-side,
followed by its own bounded acceptance before the secondary evidence is admitted to
the pool.
