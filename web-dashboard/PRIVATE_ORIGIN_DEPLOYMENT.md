# AIONEX AIOS private-origin deployment

This deployment keeps application logic, provider keys, workers, databases, and internal services on the private server. The public hosting account may serve only a landing page or reverse proxy. Never place backend source code, `.env.production`, Firebase admin credentials, provider keys, database credentials, internal prompts, or worker code on public shared hosting.

## Traffic design

`app.example.com -> Cloudflare -> Cloudflare Tunnel -> nginx:8080 -> frontend/backend`

The production Compose file binds Nginx to `127.0.0.1` only. PostgreSQL, Redis, backend, and frontend have no host ports. The optional `cloudflared` service reaches Nginx over the Docker network.

## Server actions required

1. Copy `.env.private-origin.example` to `.env.production` and replace all placeholders.
2. Set `AIOS_ALLOWED_HOSTS` to the exact application/API hostnames.
3. Set `CORS_ORIGINS` to the exact HTTPS frontend origin. Do not use `*`.
4. Create a remotely managed Cloudflare Tunnel and map its public hostname to `http://nginx:8080`.
5. Put the tunnel token in `.env.production`; never paste it into GitHub or logs.
6. Run `chmod +x scripts/validate-private-origin.sh` and execute the preflight.
7. Start with `docker compose --env-file .env.production -f docker-compose.production.yml --profile tunnel up -d --build`.
8. After confirming the tunnel works, block public inbound TCP 80/443 to the origin. Restrict SSH to the owner's address or a zero-trust access layer.
9. If the server IP was previously published in DNS, rotate the IP before launch and remove old DNS records.
10. Make the GitHub repository private and rotate every credential that has ever appeared in repository history, screenshots, logs, chat, or shell history.

## Cloudflare controls

Enable WAF managed rules, bot protection, DDoS protection, rate limiting for authentication paths, and Access protection for owner/admin routes. Configure TLS mode as strict. Do not create an unproxied DNS record pointing to the server IP.

## Frontend hosting separation

A separate hosting provider can serve a marketing site at `www.example.com`. The authenticated AIOS application should be on a protected hostname such as `app.example.com`. The marketing site must not contain backend source, secrets, private API URLs, internal prompts, or privileged tokens. Browser code is inherently inspectable; critical authorization and paid-feature checks must remain in the backend.

## Security properties implemented by this repository

- no public database, Redis, backend, or frontend container ports
- origin Nginx bound to loopback only
- optional Cloudflare Tunnel sidecar
- production host allowlist
- exact CORS methods and headers
- disabled API documentation in production
- disabled public browser source maps
- strict response security headers and CSP
- authentication/API rate limits and connection limits
- hidden server versions and no-index headers
- preflight checks for wildcard origins, weak secrets, source maps, Compose validity, and common committed-secret patterns

## Remaining infrastructure responsibilities

Repository code cannot create the owner's Cloudflare account, DNS records, tunnel token, firewall policy, encrypted disk, private GitHub visibility, or rotate external credentials. Those steps must be completed by the owner on the server and provider dashboards before the origin can be considered private.
