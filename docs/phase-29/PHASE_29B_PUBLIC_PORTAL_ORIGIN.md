# Phase 29B — Server-Managed Public Portal Origin

## Status

The first Phase 29B delivery removes the deployment dependency on a third-party document root by adding a dedicated AIONEX-managed portal container and localhost-only origin listener.

This delivery does not mark all of batch 29B complete. The verified origin must still become the active origin for `ai.vip-e.net`, and the complete public portal and Owner CMS acceptance suite must pass against that hostname.

## Production separation

The live production Compose stack now defines three distinct Nginx listeners:

- `127.0.0.1:8080` — public API gateway for `api.vip-e.net`;
- `127.0.0.1:8081` — private Super Owner control plane for `gabarot.vip-e.net`;
- `127.0.0.1:8082` — public user portal origin intended only for `ai.vip-e.net`.

The portal listener never proxies private API routes. Browser API traffic uses `https://api.vip-e.net/api/v1`, preserving the existing API allowlist, rate limits, tenant protections, and `X-AIOS-Auth-Channel: public` boundary.

## Portal image

The `portal` service builds `vip-frontend` v1.6.0 as a non-root Next.js standalone image.

The image:

- uses Node 24;
- installs dependencies with `npm ci`;
- embeds the public API origin only;
- contains no provider key, database credential, tunnel token, or Owner session;
- runs as the unprivileged `nextjs` user;
- has a health check against `/en/`;
- is not published on a public host port.

Nginx exposes the portal origin only on localhost port `8082`. Cloudflared can reach `nginx:8082` through the internal Compose network after the public hostname is assigned to the tunnel.

## Isolated acceptance evidence

The standalone portal image was built and run in an isolated container before deployment.

Verified results:

- six locales: Arabic, English, French, German, Spanish, and Turkish;
- eleven routes per locale;
- total localized routes checked: `66`;
- failed routes: `0`;
- `robots.txt`: `200`;
- `sitemap.xml`: `200`;
- `manifest.webmanifest`: `200`;
- service worker: `200`;
- icon: `200`;
- full governed project-cycle marker: present;
- final Owner approval control: present;
- delivery-package download control: present;
- Content Security Policy: present;
- `X-Frame-Options: DENY`: present;
- `X-Content-Type-Options: nosniff`: present.

## Live-hostname activation boundary

The current Cloudflare tunnel is remotely configured with:

- `api.vip-e.net` → `http://nginx:8080`;
- `gabarot.vip-e.net` → `http://nginx:8081`.

The stored credential is a connector-only tunnel token. A safe Cloudflare API capability probe returned error code `9106`, confirming that the token cannot modify the remote tunnel configuration or DNS records.

Therefore no DNS or tunnel configuration is changed by this delivery. Batch 29B remains open until an account-scoped Cloudflare credential is available to add:

- `ai.vip-e.net` → `http://nginx:8082`;

and the hostname passes the complete live acceptance suite. No secret value belongs in Git, Compose, command output, or the Owner database.

## Portal CMS live acceptance and cache correction

The production Owner CMS was exercised through the private API without exposing the Super Owner credential. A non-visual acceptance marker was saved to the draft, published as a new version, observed in the retained publication history, rolled back to the original version, and removed from the current public configuration. The draft and published configuration hashes were restored to their original values. The operation produced durable publication history and audit evidence.

This acceptance exposed a real middleware defect: the public portal endpoints correctly emitted `ETag` and public cache directives, but the global API security middleware replaced those directives with `Cache-Control: no-store`.

The corrected contract preserves explicit public caching only when all of the following are true:

- the request method is `GET` or `HEAD`;
- the response status is `200` or `304`;
- the path is exactly `/api/v1/portal/published` or a valid 32-hex portal asset path;
- the endpoint explicitly emitted a `public` cache directive.

Every mutation, Owner API, error response, malformed asset path, and other API route continues to receive `Cache-Control: no-store`. Focused isolated PostgreSQL/Redis tests cover the public configuration, ETag/304 behavior, immutable asset path, private APIs, mutations, errors, and invalid paths.

## Fixed-purpose Cloudflare activation operator

`scripts/phase29b/activate_portal_hostname.py` closes the external hostname step without accepting an arbitrary hostname, origin, tunnel, zone, or filesystem path.

It reads one external root-only file:

`/root/.config/aionex/cloudflare/phase29b-portal.env`

The file contract is exact:

- owner: `root:root`;
- directory mode: `0700`;
- file mode: `0600`;
- `CLOUDFLARE_API_TOKEN`;
- `CLOUDFLARE_ACCOUNT_ID`;
- `CLOUDFLARE_ZONE_ID`;
- no extra or duplicate variables;
- no placeholders.

The scoped API token must have Zone Read, DNS Write, and Cloudflare Tunnel Write for the AIONEX account and `vip-e.net` zone. The operator derives the existing production tunnel identity from the external connector token without returning either credential.

`--check` performs read-only verification. `--apply` can only:

1. verify the API token, account, zone, and remotely managed production tunnel;
2. preserve the existing `api.vip-e.net → nginx:8080` route;
3. preserve the existing `gabarot.vip-e.net → nginx:8081` route and its per-route settings;
4. add or correct `ai.vip-e.net → nginx:8082` before the mandatory `http_status:404` catch-all;
5. create or replace one proxied CNAME to the current tunnel;
6. verify tunnel and DNS state after the mutation;
7. restore the original tunnel configuration automatically if the DNS mutation fails.

It rejects duplicate hostnames, multiple catch-all rules, changed existing production routes, non-CNAME DNS conflicts, inactive tokens, wrong accounts or zones, locally managed tunnels, unsafe secret files, and unsuccessful verification. Its JSON result contains no token, connector secret, Authorization header, raw API body, account ID, zone ID, or tunnel ID.

## Browser accessibility and responsive acceptance

The current portal image was rebuilt after correcting the two defects found by the first real-browser audit:

- configured About pages now retain a visible localized `h1` before CMS-managed sections;
- the Facebook authentication button uses an accessible darker blue while preserving white text.

A fresh Chromium acceptance run used both a `390 × 844` mobile viewport and a `1440 × 900` desktop viewport. It covered Arabic, English, French, German, Spanish, and Turkish across home, About, Contact, Pricing, Login, Register, Privacy, and Terms.

Verified result:

- pages checked: `96`;
- HTTP failures: `0`;
- WCAG 2 A/AA, WCAG 2.1 AA, and WCAG 2.2 AA violation pages: `0`;
- accessibility violation nodes: `0`;
- horizontal-overflow failures: `0`;
- language-direction failures: `0`;
- missing-main or missing-`h1` failures: `0`;
- duplicate-ID failures: `0`;
- keyboard-focus checks: `36`, all passed;
- mobile navigation checks: `6`, all passed.

Static regression tests require the configured About branch to retain its visible `h1` and prohibit restoration of the insufficient-contrast Facebook color.
