# Phase 36G — Identity Media Production Closeout — 2026-09-08

## Scope

This receipt closes the production activation of governed Identity Media for launch. The user-facing surface is published on `ai.vip-e.net`; Super Owner controls are present on the private Owner surface; production runtime is active through the dedicated `identity-media-worker` and the existing Replicate account.

The launch contract is intentionally split:

- fictional/inspired identities: direct access when the runtime is ready;
- self / consented real-person identity: deny-by-default until Super Owner grant plus the applicable subject-rights evidence;
- licensed public figures/artists: visible product scope, but execution remains fail-closed until a valid licensed-catalog authority exists; an Owner grant is not treated as a likeness license.

## Source and protected merge

- Feature PR: `#596`.
- Merge commit: `fc74c85f8f05b7d6db2000d77caea59958bb90a2`.
- All required PR checks passed before merge, including Backend Tests, Production Docker Build, CodeQL Python/JavaScript, SBOM/vulnerability gate, Dependency Security, Core Owner/Release/Web Contracts, Owner/VIP browser boundaries, both frontend validation paths, repository secret/hygiene audit and Phase 36 reporting invariant.
- No branch-protection bypass was used.

## Pre-deploy protection

Before the production schema/runtime change, a protected platform backup was queued and completed:

- Backup ID: `f46a295d-c30c-4ad0-ab17-2d0c2f21c1ea`.
- Local status: `completed`.
- Off-site status: `completed`.
- Error: none.

The active shared-hosting user portal was also backed up before publication:

- Deployment route: `aionex-cpanel-ai-vip:/home2/ipdom3m7/ai.vip-e.net/`.
- Remote backup root: `/home2/ipdom3m7/.aionex-deploy-backups/20260908T202404Z-identity-media-launch/`.
- Archive: `ai-vip-before-identity-media.tar.gz`.
- Archive mode: `0600`.

## Production schema and runtime activation

- Alembic upgraded from `20260907_0045` to `20260908_0046` successfully.
- Production Backend, Owner frontend and VIP staging portal were rebuilt/recreated from the merged source.
- Dedicated `identity-media-worker` was launched from the production compose profile.
- Final worker health: `healthy`.
- Final worker restarts: `0`.
- Recent post-recreate worker error/traceback hits: `0`.
- Production container snapshot after cleanup: `36` running containers, `0` unhealthy, aggregate restart count `0`.

## User portal publication

The authoritative `ai.vip-e.net` publication path remains the established shared-hosting route; no DNS or Cloudflare Tunnel mutation was made.

- `npm ci --ignore-scripts`: PASS, 0 vulnerabilities reported by npm audit for the installed tree.
- `npm run verify:static`: PASS.
- Integrity: `102` source files, all `6` locales complete, no simulated-data markers.
- Static build: `139/139` pages generated.
- Static smoke: `94` URLs PASS.
- `rsync --delete` preserved hosting-owned `cgi-bin/` and `.well-known/acme-challenge/`.
- Local/remote package-owned manifest parity: EXACT, `349/349` files.
- All six localized live Identity Media routes returned HTTP `200`:
  - `/ar/studio/identity-media/`
  - `/de/studio/identity-media/`
  - `/en/studio/identity-media/`
  - `/es/studio/identity-media/`
  - `/fr/studio/identity-media/`
  - `/tr/studio/identity-media/`
- `https://api.vip-e.net/ready`: HTTP `200`.

## Owner governance acceptance

A rollback-only production transaction probe verified the effective-access contract without persisting test grants:

- fictional/inspired `voice_clone`: `allowed=true`, reason `fictional-direct`;
- real-person self identity before Owner grant: `allowed=false`, `owner_approval_required=true`, reason `owner-approval-required`;
- after Super Owner grant: `allowed=true`, reason `owner-grant`;
- after Super Owner deny/revoke: `allowed=false`, reason `owner-deny`;
- transaction rollback restored the original deny-by-default state.

The Owner UI therefore controls per-user real-person Identity Media access with grant, deny/revoke and scope controls while the rights/license gate remains separately enforced.

## Real provider canary

A real production provider canary was executed with a generated fictional illustrated face, not a real person's likeness:

- Successful execution ID: `18db5db8-cd77-4929-af04-070464718a5e`.
- Operation: `avatar_generation`.
- Identity basis: `fictional_inspired`.
- Provider state: `succeeded`.
- Final status: `completed`.
- Output: validated `video/mp4` stored privately.
- Output size: `996342` bytes.
- Output checksum: present.
- Provider-reported actual dollar cost was not asserted; the durable cost basis remains `user_authorized_ceiling_provider_price_unverified`.

An earlier operator-only direct probe was intentionally not accepted as product evidence because it was executed as container root and created root-owned test input paths. The test-only Identity Media hierarchy was immediately normalized back to `aionex:aionex` with private directory/file modes, and the successful canary above was rerun as UID/GID `1000:1000`, matching the production application/worker access boundary. The worker was then recreated; final health and logs are clean.

## Final launch status

Identity Media launch activation is complete for the currently accepted runtime operations:

- Voice Clone — runtime integrated; real-person use remains Owner/rights governed.
- Talking Head / Avatar — runtime integrated.
- Face Reenactment — runtime integrated under the same identity policy.
- Lip Sync — runtime integrated.
- Fictional / inspired identity use — direct where the operation runtime is accepted.
- Self / consented identity use — Super Owner grant plus rights evidence.
- Public-figure / artist imitation — not silently licensed by Owner approval; execution remains fail-closed unless a licensed-catalog authority is connected.
- Voice Transform and Face Swap remain visible product scope only where their runtime acceptance is still pending; they are not falsely reported as live.

No AWS/Bedrock/XR, mobile-store publication, deferred payment-gateway work, or Namecheap disk-encryption external gate was changed by this closeout.
