# Security Policy

## Supported branch

Security fixes are prepared against `main`. Production deployments must use a commit whose required GitHub checks have passed.

## Reporting vulnerabilities

Do not publish vulnerabilities, credentials, production addresses, access tokens, private prompts, customer data, or exploit details in public issues or pull requests. Contact the repository owner privately and include:

- affected commit and component;
- reproducible steps with secrets removed;
- impact and required privileges;
- suggested mitigation when known.

## Secret exposure response

A committed or logged secret is considered compromised even after deletion. Immediately revoke and rotate it, invalidate active sessions where applicable, inspect audit logs, and rewrite repository history only after rotation. Never reuse the exposed value.

## Production security requirements

- Keep the repository private before production use.
- Expose only the loopback-bound gateway through the approved private tunnel.
- Do not publish PostgreSQL, Redis, backend, worker, or frontend container ports.
- Store production secrets outside Git and mount them read-only with least privilege.
- Require exact host and CORS allowlists; wildcard production policies are forbidden.
- Keep API documentation, debug mode, framework disclosure, and browser source maps disabled.
- Run the private-origin validator and all required CI checks before deployment.
- Back up encrypted data and regularly test restoration.

## Scope limitations

Repository controls cannot change DNS, cloud firewalls, disk encryption, GitHub visibility, provider credentials, or Cloudflare configuration. Those owner-controlled actions remain mandatory before public launch.
