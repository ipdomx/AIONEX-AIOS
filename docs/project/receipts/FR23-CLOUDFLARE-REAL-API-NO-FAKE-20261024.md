# FR23: remove false Cloudflare integration success (source-only)

Protected source base: b3bfa04a8b2fa628cfa57452379255fe82174a85.

## Issue independently verified in source

The Cloudflare integration previously marked itself CONNECTED as soon as any
credential object was present, without contacting Cloudflare. Its health check
reported the API as reachable without network verification, while all
advertised operations returned request echoes without DNS, zone or account
calls. That could mislead release acceptance and DNS operators.

## Source-level correction

- Restrict the API endpoint to the official Cloudflare HTTPS v4 host.
- Require an actual Credential.token and verify it through the authenticated
  GET /user/tokens/verify response with success=true and status=active.
- Recheck actual token status on health calls; report FAILED on API errors.
- Use normal TLS certificate verification, but reject redirects and untrusted
  proxy environment variables when transporting bearer credentials.
- Bound API response sizes and reject malformed or failed result envelopes,
  without echoing token values or raw provider response/error bodies.
- Implement actual limited read-only accounts, zones and DNS record listing.
- Implement read-only zone HSTS/security header settings query.
- Validate all DNS zone and record path IDs and supported DNS record fields.
  DNS create, patch, delete require approved=True and guarded validation.
- Do not advertise formerly mock-only unsupported Cloudflare capabilities.
- No Worker code or running Worker state changed in this source proposal.

## Scope and safeguards

All tests use in-memory fake HTTP transport and synthetic credentials. No
production token, Cloudflare account, customer data or worker was accessed.
The tests verify truthful API request methods, resource paths, credential
rejection, error redaction, and mutation approval. They do not constitute
live vendor API access or authorization to alter Cloudflare DNS/settings.

Public HTTPS observation at 2026-10-24: the apex vip-e.net response omitted
Strict-Transport-Security, whereas the portal and API hostname responses
included it. This source patch does not alter that live header. The new
zone_security_headers read-only capability can inspect actual HSTS settings
only when an appropriately scoped legitimate token is separately connected.

Any future HSTS modification must separately consider subdomains, preloading,
rollback and user impact. No FR25 final release admission is inferred.

Cloudflare API docs:
https://developers.cloudflare.com/api/resources/user/subresources/tokens/methods/verify/
https://developers.cloudflare.com/api/resources/dns/subresources/records/
https://developers.cloudflare.com/api/resources/zones/subresources/settings/methods/get/
