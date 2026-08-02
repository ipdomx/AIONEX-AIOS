# AIONEX VIP authentication release v1.1.0

Apply this archive at the root of `ipdomx/AIONEX-AIOS` on top of `main`
commit `f3c6b44d5180ae9f0749ff7b755ad9d9885bf97f`.

This release contains:

- the production `vip-frontend` application;
- verified Firebase OAuth/OIDC for Google, Apple, Facebook, X and Instagram;
- one-use social-registration assertions stored in Redis;
- WebAuthn passkey registration, login, listing and revocation;
- PostgreSQL models and Alembic migration `20260802_0005`;
- production environment and Compose integration for `vip-e.net` and
  `api.vip-e.net`.

No credentials or provider secrets are included. Before deployment, copy the
production environment example to the protected runtime environment, replace
all placeholders, mount the Firebase Admin service-account file, and enable the
five providers in Firebase Authentication. Instagram uses the configurable
Firebase OIDC provider ID `oidc.instagram`.

The production backend container runs `alembic upgrade head` before startup.
The production Compose frontend service builds `vip-frontend` and proxies
browser requests from `/api/v1` to the internal backend service.

Full deployment and verification instructions are in
`docs/VIP_FRONTEND_AUTH_DEPLOYMENT.md`.
