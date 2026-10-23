# FR09 / Cloudflare Tunnel trusted client identity - source-only proposal

Protected main: a8b2ac8a7d4d6fa73c81216c1f0180bddb0dcf05.

## Proven deployment topology and capacity defect

The production Nginx container receives HTTP ingress from the single
Cloudflared Docker peer. Current limit_req_zone and limit_conn_zone keys
use Nginx binary_remote_addr, which represents that TCP peer by default.
Independent visitors can therefore share a single tunnel-level request
quota. This architecture cannot prove distinct per-client rate limiting
at the required 5,000-user scale. The private Owner /api ingress proxies
directly to Backend through Nginx, not via Next.js rewrites.

## Protected source-only remediation

The immutable production Nginx and Docker Compose sources remain unchanged.
The optional docker-compose.fr09-trusted-realip.yml overlay mounts an extra
root-managed trusted-peer directory read-only, then uses
nginx-fr09-realip-entrypoint.sh to insert one optional include inside the
existing HTTP configuration in private tmpfs. It validates the final Nginx
syntax and starts Nginx only after validation.

The operator script fr09_cloudflared_realip_admission.py checks the actual
live Docker Compose service and project labels for both Nginx and Cloudflared,
their running state, and their exact matching private Docker IPv4 network.
It renders only the live Cloudflared container's IPv4 /32 as set_real_ip_from
with real_ip_header CF-Connecting-IP and real_ip_recursive off. All other
peers, including other service containers on the same bridge, continue to
use their actual TCP peer address and cannot spoof CF-Connecting-IP for
per-client rate-limit avoidance.

On a cold start, the include may be empty until Cloudflared is created.
Nginx still starts fail-closed with TCP-peer-based throttling; source files
do not depend on the Cloudflared hostname resolving at startup.

## Admission, lifecycle, and rollback

- Keep the overlay inactive until protected exact-head CI, isolated syntax
  validation, identity/spoof boundary acceptance, approved production
  change window, rollback proof, and NS12 continuity handling.
- Operator may run the script without --apply for read-only peer admission.
  When separately authorized, --apply creates or updates a single
  root-owned trusted-cloudflared.conf in
  /var/lib/aionex-migration/fr09-trusted-realip. It never signals Nginx.
- After any Cloudflared recreation the tunnel container IP may change.
  Recheck, stage the new /32 file, verify Nginx syntax and then independently
  authorize a graceful reload; until this happens the new peer is untrusted.
  Never trust all Docker RFC1918 prefixes, X-Forwarded-For from arbitrary
  users, or a header supplied by a non-Cloudflared client.
- The overlay by itself does not qualify as a verified 5,000 authenticated
  user / 15,000 durable-job / 15-minute capacity run, or close FR06, FR08,
  FR09, FR24, or FR25. The user-facing origin and Cloudflare settings
  remain unchanged.
- Rollback: stop using the overlay, return to the original exact-head
  production Nginx/Compose inputs and retain all NS12 historical evidence,
  original host, and rollback images.

No customer source IPs, tokens or keys should be persisted in CI artifacts.
