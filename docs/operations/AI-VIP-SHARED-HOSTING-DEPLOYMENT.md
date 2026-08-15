# ai.vip-e.net Shared-Hosting Deployment Source of Truth

## Current production route

As of 2026-08-15, the active `ai.vip-e.net` user portal is served from the existing cPanel/shared-hosting document root. Routine VIP frontend releases are deployed there directly from the AIOS server; they do **not** require a Cloudflare DNS or Tunnel mutation.

- Public user portal: `https://ai.vip-e.net`
- SSH alias from the AIOS server: `aionex-cpanel-ai-vip`
- SSH account: `ipdom3m7`
- SSH host: `ipdomx.com`
- SSH port: `22`
- SSH identity path: `/root/.ssh/aionex_cpanel_ai_vip_e_net_ed25519`
- Identity file requirement: root-owned, mode `0600`; never read, print, copy, or commit the key material.
- User-portal document root: `/home2/ipdom3m7/ai.vip-e.net`
- Public-site document root: `/home2/ipdom3m7/vip-e.net`
- Remote deployment backups: `/home2/ipdom3m7/.aionex-deploy-backups/`

The ChatGPT-connected `AIONEX Server MCP 2` operates on the AIOS server and can use this already-configured SSH alias to reach the shared-hosting account. No separate Cloudflare token is needed for a normal frontend update.

## Routine VIP frontend release procedure

1. Start from a clean, merged `main` in `/opt/AIOS`.
2. Build and validate the static frontend from `/opt/AIOS/vip-frontend`:
   - `npm ci --ignore-scripts`
   - `npm run verify:static`
3. Verify the SSH alias and remote document root read-only before mutation.
4. Create a timestamped remote backup under `/home2/ipdom3m7/.aionex-deploy-backups/<timestamp>-<purpose>/`.
5. Synchronize the **contents** of `vip-frontend/out/` to `/home2/ipdom3m7/ai.vip-e.net/` with rsync.
6. Use `--delete` only with these hosting-owned exclusions preserved:
   - `cgi-bin/`
   - `.well-known/acme-challenge/`
7. Generate SHA-256 manifests on both sides using a fixed `LC_ALL=C` ordering and require an exact match for all package-owned files before accepting the release.
8. Run live HTTP acceptance against the localized user routes and public API boundary.
9. Record the backup path, source commit, test results, file-count/hash parity, and live HTTP checks in the project report and a private deployment receipt.

Reference rsync shape:

```text
rsync -az --delete \
  --exclude 'cgi-bin/' \
  --exclude '.well-known/acme-challenge/' \
  vip-frontend/out/ \
  aionex-cpanel-ai-vip:/home2/ipdom3m7/ai.vip-e.net/
```

The command above documents the deployment contract only. Operators must still perform a dry run and remote backup first.

## Separation boundaries

- `ai.vip-e.net` is the normal user portal.
- `api.vip-e.net` is the public API boundary and remains server-side.
- `gabarot.vip-e.net` is the private Super Owner surface protected by Cloudflare Access.
- Updating `ai.vip-e.net` static files must not change `api.vip-e.net`, `gabarot.vip-e.net`, DNS, the Cloudflare Tunnel, or Owner access policy.
- The server-managed portal container on `nginx:8082` is an alternate/staging origin capability. It is **not** a reason to replace the active shared-hosting route during a routine UI release. Any future architecture migration from shared hosting to the tunnel must be an explicit Owner-approved infrastructure change with separate backup, validation, and rollback evidence.

## Security rules

- Never place provider credentials, `.env.production`, database credentials, Cloudflare tokens, SSH private keys, internal prompts, or backend source in the shared-hosting document root.
- Browser assets are public by definition; authorization and paid-feature enforcement stay in the Backend/API.
- Do not invent or regenerate hosting credentials when the existing SSH route is healthy.
- Do not create a Cloudflare API token merely to publish a VIP frontend update.
- A Cloudflare API token is only relevant to an explicit DNS/Tunnel architecture change, not routine static deployment.

## 2026-08-15 campaign-advisor deployment evidence

- Source commit: `9b02683a976178405a7d9fe734bca9cbe984cf90` (PR #363 merged).
- Static validation: integrity PASS (`90` source files, `6` complete locales), TypeScript PASS, lint PASS, build PASS (`115/115` pages), static smoke PASS (`94` URLs).
- Remote pre-deploy backup: `/home2/ipdom3m7/.aionex-deploy-backups/20260815T191130Z-ai-vip-before-campaign-advisor`.
- Rsync dry run reviewed before mutation; all deletions were stale Next.js build assets only.
- Package-owned SHA-256 parity after deployment: `296/296` exact file matches with fixed `LC_ALL=C` ordering.
- Live campaign pages: `/ar/campaigns/`, `/en/campaigns/`, `/fr/campaigns/`, `/de/campaigns/`, `/es/campaigns/`, `/tr/campaigns/` all returned HTTP `200` and contained campaign-page markers.
- Additional live checks: `/en/login/` HTTP `200`; `/ar/projects/` HTTP `200`; `/.well-known/assetlinks.json` HTTP `200`.
- Public user paid-campaign API unauthenticated boundary: HTTP `401`.
- Public Owner paid-campaign API boundary: HTTP `404`.
- Private Owner hostname remains behind Cloudflare Access (unauthenticated request redirects to Access).
- Cloudflare DNS/Tunnel changes: **NONE**.
- Cloudflare Account API token created/used for this release: **NO**.
