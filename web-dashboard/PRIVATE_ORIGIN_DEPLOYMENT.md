# AIONEX AIOS private-origin deployment

This deployment keeps application logic, provider keys, workers, databases, and internal services on the private server. The public hosting account may serve only a landing page or reverse proxy. Never place backend source code, `.env.production`, Firebase admin credentials, provider keys, database credentials, internal prompts, or worker code on public shared hosting.

## Traffic design

`api.example.com -> Cloudflare -> Cloudflare Tunnel -> nginx:8080 -> backend only`

`private-control.example.com -> Cloudflare Access -> Cloudflare Tunnel -> nginx:8081 -> frontend/backend`

`user-portal.example.com -> Cloudflare -> Cloudflare Tunnel -> nginx:8082 -> public portal only`

The production Compose file binds all three Nginx listeners to `127.0.0.1` only. The public API listener on `8080` returns `404` for dashboard pages and unlisted API paths, exposes only the user-portal contracts plus health/WebSocket access, and stamps requests as the public authentication channel. Super Owner sessions are rejected on that channel. The private listener on `8081` stamps the private authentication channel, serves the control plane, and must be protected by Cloudflare Access. The public portal listener on `8082` serves only the VIP portal and returns `404` for local API and WebSocket paths; browser API traffic uses the separately protected API hostname. PostgreSQL, Redis, backend, Owner frontend, and portal have no public host ports.

## Server actions required

1. Copy `.env.private-origin.example` to `.env.production` and replace all placeholders.
2. Choose a non-publicized control hostname, store it as `AIOS_CONTROL_HOST`, and include that exact value plus the API hostname in `AIOS_ALLOWED_HOSTS`. Never commit the real control hostname.
3. Set `CORS_ORIGINS` and `AIOS_PUBLIC_PORTAL_ORIGINS` to the exact HTTPS user-portal origin. Set `AIOS_USER_PORTAL_URL` to the same public entry point. Do not use `*`.
4. Map the public API hostname to `http://nginx:8080`. Map `AIOS_CONTROL_HOST` to `http://nginx:8081` and require Cloudflare Access before the tunnel route. Map the public user-portal hostname to `http://nginx:8082` without exposing the listener directly.
5. Put the tunnel token in `.env.production`; never paste it into GitHub or logs.
6. Run `chmod +x scripts/validate-private-origin.sh` and execute the preflight.
7. Start with `docker compose --env-file .env.production -f docker-compose.production.yml --profile tunnel up -d --build`.
8. After confirming the tunnel works, block public inbound TCP 80/443 to the origin. Restrict SSH to the owner's address or a zero-trust access layer.
9. If the server IP was previously published in DNS, rotate the IP before launch and remove old DNS records.
10. Make the GitHub repository private and rotate every credential that has ever appeared in repository history, screenshots, logs, chat, or shell history.

## Cloudflare controls

Enable WAF managed rules, bot protection, DDoS protection, rate limiting for authentication paths, and Access protection for the entire private control-plane hostname. Configure TLS mode as strict. Do not create an unproxied DNS record pointing to the server IP.

## Frontend hosting separation

The preferred production path serves the public AIONEX user portal from the dedicated `portal` container through the localhost-only `8082` origin and Cloudflare Tunnel. `ai.vip-e.net` remains the only public registration/user sign-in surface and contains no privileged control-plane link.

A separate static hosting provider may be retained only as a temporary migration path. It must not contain backend source, secrets, origin addresses, internal prompts, or privileged tokens. Browser code is inherently inspectable, and the API gateway hostname is also discoverable; critical authorization and paid-feature checks remain server-side.

## Security properties implemented by this repository

- no public database, Redis, backend, Owner frontend, or portal container ports
- origin Nginx bound to loopback only
- optional Cloudflare Tunnel sidecar
- production host allowlist
- exact CORS methods and headers
- disabled API documentation in production
- disabled public browser source maps
- strict response security headers and CSP
- authentication/API rate limits and connection limits
- public API contract allowlist and public/private authentication-channel enforcement
- Super Owner rejection on the public user portal
- hidden server versions and no-index headers
- preflight checks for wildcard origins, weak secrets, source maps, Compose validity, and common committed-secret patterns

## Remaining infrastructure responsibilities

Repository code cannot create the owner's Cloudflare account, DNS records, tunnel token, firewall policy, encrypted disk, private GitHub visibility, or rotate external credentials. Those steps must be completed by the owner on the server and provider dashboards before the origin can be considered private.
